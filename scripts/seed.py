"""
Seed script — creates an admin account and optional test data.

Usage:
  python scripts/seed.py
  python scripts/seed.py --with-test-data
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal, engine
from app.db.session import Base
from app.models.user import User, UserRole
from app.core.security import hash_password

Base.metadata.create_all(bind=engine)

ADMIN_EMAIL = "admin@datamarket.io"
ADMIN_PASSWORD = "Admin1234!"


def seed():
    db = SessionLocal()

    # Admin user
    existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not existing:
        admin = User(
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            full_name="DataMarket Admin",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        db.commit()
        print(f"✅ Admin created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    else:
        print(f"ℹ️  Admin already exists: {ADMIN_EMAIL}")

    # Optional test users
    if "--with-test-data" in sys.argv:
        test_users = [
            ("seller@test.com", "Seller1234!", "Test Seller", UserRole.SELLER),
            ("buyer@test.com", "Buyer1234!", "Test Buyer", UserRole.BUYER),
        ]
        for email, password, name, role in test_users:
            if not db.query(User).filter(User.email == email).first():
                user = User(
                    email=email,
                    hashed_password=hash_password(password),
                    full_name=name,
                    role=role,
                    is_active=True,
                    is_verified=True,
                )
                db.add(user)
                print(f"✅ Test user: {email} / {password}")
        db.commit()

    db.close()
    print("\n🌱 Seed complete.")


if __name__ == "__main__":
    seed()
