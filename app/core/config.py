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

    # Storage
    STORAGE_BUCKET: str = "datamarket-datasets"
    STORAGE_REGION: str = "eu-west-3"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SIGNED_URL_EXPIRY_SECONDS: int = 3600

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

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
