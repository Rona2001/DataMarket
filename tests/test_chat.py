"""
Datia chatbot tests — context building, retrieval, sanitising, limits, streaming,
request drafts and seller insights. The LLM is always mocked.
"""
import json
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from app.core import llm
from app.core.config import settings
from app.core.security import get_current_user, get_current_active_seller, hash_password
from app.models.chat import ChatLog, ChatQuestion
from app.models.dataset import Dataset, DatasetStatus, DataFormat
from app.models.user import User, UserRole
from app.services import chat_service
from main import app


def make_user(db, email, premium=False, role=UserRole.BUYER):
    user = User(email=email, hashed_password=hash_password("Passw0rd!"), full_name=email.split("@")[0],
                role=role, is_premium=premium)
    db.add(user)
    db.commit()
    return user


def make_dataset(db, seller, title, category, tags, description, columns, price=10.0, status=DatasetStatus.PUBLISHED):
    ds = Dataset(
        seller_id=seller.id, title=title, slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        description=description, category=category, tags=tags, data_format=DataFormat.CSV,
        num_rows=1000, num_columns=len(columns), price=price, is_free=price == 0, quality_score=88.0, status=status,
        schema_info={"columns": [
            {"name": c, "dtype": "object", "null_pct": 1.0, "sample_values": ["a", "b"], "distinct_count": 12,
             "top_values": [{"value": "FR", "pct": 60.0}]} for c in columns]},
        verification_report={"steps": {"pii_scan": {"risk_level": "none"},
                                       "quality_score": {"dimensions": {"completeness": {"score": 97}}}}},
        download_count=0, published_at=datetime(2026, 8, 1),
    )
    db.add(ds)
    db.commit()
    return ds


@pytest.fixture
def world(db):
    seller = make_user(db, "seller@x.com", role=UserRole.SELLER)
    return {
        "seller": seller,
        "free": make_user(db, "free@x.com"),
        "premium": make_user(db, "premium@x.com", premium=True),
        "nlp": make_dataset(db, seller, "French NLP corpus", "NLP", ["nlp", "french"], "2M French sentences", ["text", "label"]),
        "housing": make_dataset(db, seller, "Paris real estate prices", "Real Estate", ["housing"],
                                "Transactions immobilières à Paris", ["price_eur", "surface"], price=49),
        "draft": make_dataset(db, seller, "Hidden draft", "NLP", ["nlp"], "not live", ["x"], status=DatasetStatus.DRAFT),
    }


def capture(answer="ok"):
    seen = {}

    def fake(system, turns, **kwargs):
        seen["system"], seen["turns"] = system, turns
        return answer(seen) if callable(answer) else answer
    return seen, fake


class TestContext:
    def test_current_dataset_needs_no_name(self, db, world):
        seen, fake = capture()
        with patch.object(llm, "complete", fake):
            res = chat_service.ask(db, world["premium"], "what columns does it have?", [], str(world["nlp"].id))
        assert "CURRENT DATASET" in seen["system"]
        assert "text · object · 1.0% null · 12 distinct · most frequent: FR 60.0%" in seen["system"]
        assert res["context_dataset"] == {"id": str(world["nlp"].id), "title": "French NLP corpus"}
        assert res["premium_required"] is False

    def test_free_plan_gets_listing_only(self, db, world):
        seen, fake = capture()
        with patch.object(llm, "complete", fake):
            res = chat_service.ask(db, world["free"], "what columns does it have?", [], str(world["nlp"].id))
        current = seen["system"].split("--- MARKETPLACE CANDIDATES")[0]
        assert "text · object" not in current and "free plan" in current
        assert res["premium_required"] is True

    def test_unpublished_page_falls_back_to_marketplace(self, db, world):
        seen, fake = capture()
        with patch.object(llm, "complete", fake):
            res = chat_service.ask(db, world["free"], "hello", [], str(world["draft"].id))
        assert res["context_dataset"] is None and "not on a dataset page" in seen["system"]
        assert "Hidden draft" not in seen["system"]


class TestDiscovery:
    def test_ranks_matching_dataset_first_and_excludes_current(self, db, world):
        shortlist, hits = chat_service.find_candidates(db, "housing prices in Paris", exclude_id=world["nlp"].id)
        assert shortlist[0].title == "Paris real estate prices"
        assert [d.title for d in hits] == ["Paris real estate prices"]
        assert all(d.id != world["nlp"].id for d in shortlist)

    def test_recommended_datasets_become_cards_and_fake_links_are_dropped(self, db, world):
        ghost = uuid.uuid4()
        answer = f"Try [Paris real estate prices](/dataset/{world['housing'].id}) or [Ghost](/dataset/{ghost})."
        with patch.object(llm, "complete", capture(answer)[1]):
            res = chat_service.ask(db, world["free"], "I need housing prices", [])
        assert [c["title"] for c in res["datasets"]] == ["Paris real estate prices"]
        assert str(ghost) not in res["answer"] and "Ghost" in res["answer"]

    def test_large_catalogue_widens_query_with_synonyms(self, db, world):
        with patch.object(settings, "CHAT_FULL_CATALOGUE_MAX", 0), \
             patch.object(llm, "complete_json", lambda *a, **k: {"keywords": ["housing", "logement"]}):
            shortlist, hits = chat_service.find_candidates(db, "prix des appartements")
        assert [d.title for d in hits] == ["Paris real estate prices"]


class TestLimitsAndLogs:
    def test_rate_limit(self, db, world):
        with patch.object(settings, "CHAT_FREE_RATE_LIMIT_PER_HOUR", 1), patch.object(llm, "complete", capture()[1]):
            chat_service.ask(db, world["free"], "hi", [])
            with pytest.raises(Exception) as err:
                chat_service.ask(db, world["free"], "hi again", [])
        assert err.value.status_code == 429

    def test_provider_failure_is_not_counted(self, db, world):
        def boom(*a, **k):
            raise llm.LLMError("down")
        with patch.object(llm, "complete", boom):
            res = chat_service.ask(db, world["free"], "hi", [])
        assert "temporarily unavailable" in res["answer"]
        assert db.query(ChatLog).count() == 0

    def test_no_provider_uses_offline_answer(self, db, world):
        def none(*a, **k):
            raise llm.LLMUnavailable("no key")
        with patch.object(llm, "complete", none):
            res = chat_service.ask(db, world["free"], "housing", [])
        assert "/dataset/" in res["answer"] and db.query(ChatLog).count() == 1

    def test_unanswered_questions_are_logged_anonymously(self, db, world):
        with patch.object(llm, "complete", capture("[[NO_ANSWER]] The listing does not say.")[1]):
            res = chat_service.ask(db, world["premium"], "What is the sampling method?", [], str(world["nlp"].id))
        assert res["answer"] == "The listing does not say."
        row = db.query(ChatQuestion).one()
        assert row.answered is False and row.dataset_id == world["nlp"].id and not hasattr(row, "user_id")
        insights = chat_service.dataset_questions(db, world["seller"], str(world["nlp"].id))
        assert insights["total"] == 1 and insights["unanswered_total"] == 1

    def test_seller_own_questions_are_not_logged(self, db, world):
        with patch.object(llm, "complete", capture()[1]):
            chat_service.ask(db, world["seller"], "testing", [], str(world["nlp"].id))
        assert db.query(ChatQuestion).count() == 0

    def test_insights_are_owner_only(self, db, world):
        with pytest.raises(Exception) as err:
            chat_service.dataset_questions(db, world["free"], str(world["nlp"].id))
        assert err.value.status_code == 403


class TestRequestDraft:
    def test_keeps_only_valid_survey_values(self, db, world):
        model = {"domain": "Real Estate", "data_types": ["tabular", "hologram"], "volume": ">1M",
                 "intended_use": "world domination", "budget_range": "50-300", "free_text": "I need rents by city."}
        with patch.object(llm, "complete_json", lambda *a, **k: model):
            draft = chat_service.draft_request(db, world["free"], [{"role": "user", "content": "rents by city"}])
        assert draft["domain"] == "Real Estate" and draft["data_types"] == ["tabular"]
        assert draft["volume"] == ">1M" and draft["intended_use"] is None and draft["budget_range"] == "50-300"

    def test_without_model_carries_the_user_words(self, db, world):
        def none(*a, **k):
            raise llm.LLMUnavailable("no key")
        with patch.object(llm, "complete_json", none):
            draft = chat_service.draft_request(db, world["free"], [{"role": "user", "content": "rents by city"}])
        assert draft["free_text"] == "rents by city" and draft["domain"] is None


class TestRoutes:
    @pytest.fixture
    def as_user(self, world):
        def login(user):
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_current_active_seller] = lambda: user
        yield login
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_active_seller, None)

    def test_chat_requires_login(self, client):
        assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401

    def test_stream_hides_tag_and_ends_with_full_payload(self, client, world, as_user, db):
        as_user(world["premium"])
        link = f"[Paris real estate prices](/dataset/{world['housing'].id})"

        def fake_stream(system, turns, **kwargs):
            yield from ["[[NO_", "ANSWER]] Not in ", "the listing. See ", link]

        # the stream writes its logs through its own session: point it at the test DB
        from tests.conftest import TestSessionLocal
        with patch.object(llm, "stream", fake_stream), patch.object(chat_service, "SessionLocal", TestSessionLocal):
            res = client.post("/api/v1/chat/stream", json={"message": "sampling?", "dataset_id": str(world["nlp"].id)})
        assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
        streamed = "".join(e["text"] for e in events if e["type"] == "delta")
        assert "NO_ANSWER" not in streamed and streamed.startswith("Not in the listing.")
        done = events[-1]
        assert done["type"] == "done" and done["answer"].startswith("Not in the listing.")
        assert [c["title"] for c in done["datasets"]] == ["Paris real estate prices"]
        assert db.query(ChatQuestion).one().answered is False

    def test_questions_route(self, client, world, as_user):
        as_user(world["seller"])
        res = client.get(f"/api/v1/datasets/{world['nlp'].id}/questions")
        assert res.status_code == 200 and res.json()["total"] == 0
