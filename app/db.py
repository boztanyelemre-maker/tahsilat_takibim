import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# Oncelik .env icindeki DATABASE_URL; yoksa yerel SQLite dosyasina dusuyoruz.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # PostgreSQL ayari hazir degilse, MVP icin SQLite kullanalim
    DATABASE_URL = "sqlite:///./tahsilat.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


