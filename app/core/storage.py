"""
Supabase Storage client — handles all file operations.
Datasets are stored in private buckets and only served via signed URLs.
Buyers NEVER get a direct, permanent link.
"""
import uuid
from datetime import datetime
from supabase import create_client, Client
from app.core.config import settings


def get_supabase() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def build_storage_key(seller_id: str, dataset_id: str, filename: str) -> str:
    """
    Deterministic storage path:  sellers/{seller_id}/{dataset_id}/{filename}
    Keeps files organised and prevents collisions.
    """
    return f"sellers/{seller_id}/{dataset_id}/{filename}"


def upload_file(bucket: str, key: str, data: bytes, content_type: str) -> str:
    """Upload bytes to a Supabase bucket. Returns the storage key."""
    client = get_supabase()
    client.storage.from_(bucket).upload(
        path=key,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return key


def generate_signed_url(bucket: str, key: str, expires_in: int = None) -> str:
    """
    Generate a time-limited signed URL for secure file delivery.
    Default expiry = SIGNED_URL_EXPIRY_SECONDS from settings (1 hour).
    This is the ONLY way buyers access datasets.
    """
    expiry = expires_in or settings.SIGNED_URL_EXPIRY_SECONDS
    client = get_supabase()
    result = client.storage.from_(bucket).create_signed_url(key, expiry)
    return result["signedURL"]


def delete_file(bucket: str, key: str) -> None:
    """Permanently remove a file (e.g. seller deletes a dataset)."""
    client = get_supabase()
    client.storage.from_(bucket).remove([key])


def get_public_sample_url(key: str) -> str:
    """
    Sample files live in a PUBLIC bucket — anyone can preview.
    Full datasets are always private.
    """
    client = get_supabase()
    result = client.storage.from_(settings.SUPABASE_SAMPLE_BUCKET).get_public_url(key)
    return result
