import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.db.session import Base


class UserRole(str, enum.Enum):
    BUYER = "buyer"
    SELLER = "seller"
    BOTH = "both"       # most users will eventually be both
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    organization = Column(String(255), nullable=True)   # university, company, etc.

    role = Column(Enum(UserRole), default=UserRole.BUYER, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)        # email verification
    is_premium = Column(Boolean, default=False)         # paid subscription

    # Stripe customer ID for payment management
    stripe_customer_id = Column(String(255), nullable=True)

    # Profile
    bio = Column(Text, nullable=True)
    website = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Relationships (will be populated as we add other models)
    datasets = relationship("Dataset", back_populates="seller", lazy="dynamic")
    purchases = relationship("Purchase", back_populates="buyer", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
