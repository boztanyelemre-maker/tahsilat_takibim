import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
if not os.getenv("DATABASE_URL"):
    load_dotenv(_root / ".env.txt")

_SQLITE_PATH = _root / "tahsilat.db"
_DEFAULT_SQLITE_URL = f"sqlite:///{_SQLITE_PATH}"


def _sqlite_engine(url: str | None = None):
    u = url or _DEFAULT_SQLITE_URL
    return create_engine(u, connect_args={"check_same_thread": False})


def _probe_connection(engine):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _resolve_engine_and_url():
    """
    DATABASE_URL varsa onu dene; PostgreSQL kapali / erisilemez ise SQLite'a dus.
    """
    raw = os.getenv("DATABASE_URL")
    if not raw:
        eng = _sqlite_engine()
        logger.info("DATABASE_URL yok; SQLite kullaniliyor: %s", _SQLITE_PATH)
        return eng, _DEFAULT_SQLITE_URL

    if "sqlite" in raw.lower():
        eng = _sqlite_engine(raw)
        _probe_connection(eng)
        return eng, raw

    eng = create_engine(raw)
    try:
        _probe_connection(eng)
        logger.info("Veritabani baglantisi OK (DATABASE_URL).")
        return eng, raw
    except Exception as exc:
        logger.warning(
            "DATABASE_URL ile baglanti kurulamadi (%s). Yerel SQLite kullaniliyor: %s",
            exc,
            _SQLITE_PATH,
        )
        eng = _sqlite_engine()
        return eng, _DEFAULT_SQLITE_URL


engine, DATABASE_URL = _resolve_engine_and_url()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
