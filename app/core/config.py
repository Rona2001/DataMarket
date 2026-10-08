from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "DataMarket"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str

    # Database
    DATABASE_URL: str

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # Supabase Storage
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""          # service_role key (server-side only)
    SUPABASE_STORAGE_BUCKET: str = "datasets"
    SUPABASE_SAMPLE_BUCKET: str = "samples"
    SIGNED_URL_EXPIRY_SECONDS: int = 3600   # 1 hour download window

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 500
    ALLOWED_EXTENSIONS: list = ["csv", "json", "parquet", "xlsx", "zip"]
    SAMPLE_ROWS: int = 50                   # rows to expose as preview

    # Payments
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Premium subscription. Leave the price id empty to bill an inline €/month price.
    STRIPE_PREMIUM_PRICE_ID: str = ""
    PREMIUM_PRICE_EUR: float = 10.0

    # Email (Brevo) — optional; features degrade gracefully if unset
    BREVO_API_KEY: str = ""
    BREVO_SENDER_EMAIL: str = "rona.nasro@datrust.fr"  # must be a Brevo-verified sender
    BREVO_SENDER_NAME: str = "datrust"
    BREVO_QUALITY_REPORT_LIST_ID: int = 0   # 0 = don't add to any list
    BREVO_USERS_LIST_ID: int = 0            # registered users (welcome flow); 0 = don't add
    SUPPORT_EMAIL: str = "rona.nasro@datrust.fr"  # where dispute/ops notifications go

    # Verification → publication. Neither mode needs anyone at datrust to act.
    # False: the seller sees the score first and clicks publish (what /sell promises).
    # True: a dataset that passes verification goes live on its own.
    AUTO_PUBLISH_VERIFIED: bool = False

    # Free Quality Report (public lead magnet — spec §4)
    REPORT_MAX_UPLOAD_MB: int = 100          # smaller cap than paid uploads
    FREE_REPORTS_PER_EMAIL_PER_MONTH: int = 5
    FREE_REPORTS_PER_IP_PER_HOUR: int = 10
    FRONTEND_URL: str = "http://localhost:3000"

    # Category Alerts (spec §11) — max 1 alert email per user per this window
    ALERT_THROTTLE_HOURS: int = 24

    # Dataset Chatbot (spec §14) — premium pre-purchase Q&A
    # Provider is swappable via a single value (groq | mistral | ollama | claude).
    CHAT_PROVIDER: str = "groq"
    CHAT_RATE_LIMIT_PER_HOUR: int = 40          # Premium users
    CHAT_FREE_RATE_LIMIT_PER_HOUR: int = 15     # free plan (discovery + listing-level answers)
    CHAT_MAX_CANDIDATES: int = 8                # datasets shortlisted per question
    CHAT_FULL_CATALOGUE_MAX: int = 25           # at or below this many listings, pass them all
    CHAT_LOG_QUESTIONS: bool = True             # anonymous per-dataset question log for seller insights
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_FAST_MODEL: str = "openai/gpt-oss-20b"  # helper calls: query expansion, request drafts
    # Public/sovereign options, wired for later switch:
    MISTRAL_API_KEY: str = ""
    MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
    MISTRAL_MODEL: str = "mistral-small-latest"
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3.1"

    # CORS — accepts comma-separated string or JSON list
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()