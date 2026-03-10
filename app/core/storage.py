"""
Supabase Storage client — handles all file operations.
Datasets are stored in private buckets and only served via signed URLs.
Buyers NEVER get a direct, permanent link.
"""
import httpx
from app.core.config import settings


def _headers() -> dict:
    """Auth headers using service role key — bypasses RLS entirely."""
    return {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
    }


def build_storage_key(seller_id: str, dataset_id: str, filename: str) -> str:
    return f"sellers/{seller_id}/{dataset_id}/{filename}"


def upload_file(bucket: str, key: str, data: bytes, content_type: str) -> str:
    """Upload bytes directly via Supabase Storage REST API."""
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{key}"
    headers = {
        **_headers(),
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    response = httpx.put(url, content=data, headers=headers, timeout=60)
    if response.status_code not in (200, 201):
        raise Exception(f"Storage upload failed: {response.status_code} {response.text}")
    return key


def generate_signed_url(bucket: str, key: str, expires_in: int = None) -> str:
    """Generate a signed URL via Supabase Storage REST API."""
    expiry = expires_in or settings.SIGNED_URL_EXPIRY_SECONDS
    url = f"{settings.SUPABASE_URL}/storage/v1/object/sign/{bucket}/{key}"
    response = httpx.post(url, json={"expiresIn": expiry}, headers=_headers(), timeout=30)
    if response.status_code != 200:
        raise Exception(f"Signed URL failed: {response.status_code} {response.text}")
    data = response.json()
    signed_path = data.get("signedURL") or data.get("signedUrl") or data.get("signed_url", "")
    if signed_path.startswith("/"):
        return f"{settings.SUPABASE_URL}/storage/v1{signed_path}"
    return signed_path


def delete_file(bucket: str, key: str) -> None:
    """Delete a file via Supabase Storage REST API."""
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{key}"
    httpx.delete(url, headers=_headers(), timeout=30)


def get_public_sample_url(key: str) -> str:
    """Get public URL for sample files."""
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.SUPABASE_SAMPLE_BUCKET}/{key}"