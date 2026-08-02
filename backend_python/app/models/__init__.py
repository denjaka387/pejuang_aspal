from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from .base import Base



SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False))


def init_db(app: Flask) -> None:
    database_url = app.config["DATABASE_URL"]
    engine = create_engine(database_url, echo=False, future=True)
    SessionLocal.configure(bind=engine)

    # Ensure models are imported so they register with Base
    # Ensure models are imported so they register with Base
    from .user import User  # noqa: F401
    from .order import Order  # noqa: F401
    from .finance import FinanceLog  # noqa: F401
    from .device_fingerprint import (
        DeviceFingerprint,
        SubscriptionTrial,
        AntiFraudWarning,
    )  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal

