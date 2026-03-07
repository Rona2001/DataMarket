import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime,
    Enum, Text, Integer, ForeignKey, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.db.session import Base


class DatasetStatus(str, enum.Enum):
    DRAFT = "draft"               # uploaded, not yet published
    PENDING_REVIEW = "pending"    # submitted for verification
    VERIFIED = "verified"         # passed quality checks
    PUBLISHED = "published"       # live on marketplace
    REJECTED = "rejected"         # failed verification
    ARCHIVED = "archived"


class DataFormat(str, enum.Enum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"
    EXCEL = "excel"
    ZIP = "zip"
    OTHER = "other"


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Core metadata
    title = Column(String(255), nullable=False)
    slug = Column(String(300), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    tags = Column(JSON, default=list)           # ["finance", "nlp", "healthcare"]
    category = Column(String(100), nullable=True)

    # Data characteristics
    data_format = Column(Enum(DataFormat), nullable=False)
    num_rows = Column(Integer, nullable=True)
    num_columns = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    schema_info = Column(JSON, nullable=True)   # column names, types, descriptions
    update_frequency = Column(String(50), nullable=True)  # "daily", "monthly", "static"

    # Storage (S3 keys — never exposed directly to buyers)
    storage_key = Column(String(500), nullable=True)          # full dataset
    sample_storage_key = Column(String(500), nullable=True)   # preview sample

    # Pricing
    price = Column(Float, nullable=False, default=0.0)        # EUR
    is_free = Column(Boolean, default=False)

    # Legal & compliance
    license_type = Column(String(100), nullable=True)         # "CC BY 4.0", "proprietary"
    data_origin = Column(Text, nullable=True)                 # how was the data collected
    contains_pii = Column(Boolean, default=False)             # personally identifiable info
    gdpr_compliant = Column(Boolean, default=False)
    usage_restrictions = Column(Text, nullable=True)

    # Quality & verification
    status = Column(Enum(DatasetStatus), default=DatasetStatus.DRAFT)
    quality_score = Column(Float, nullable=True)              # 0-100, set by verification
    verification_report = Column(JSON, nullable=True)         # full report from pipeline
    checksum = Column(String(64), nullable=True)              # SHA-256 of file

    # Stats
    view_count = Column(Integer, default=0)
    download_count = Column(Integer, default=0)
    average_rating = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    # Relationships
    seller = relationship("User", back_populates="datasets")
    purchases = relationship("Purchase", back_populates="dataset", lazy="dynamic")

    def __repr__(self):
        return f"<Dataset '{self.title}' ({self.status})>"
