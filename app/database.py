import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Using SQLite for easy self-hosting out of the box
# Override with TRIPPY_DATABASE_URL (the Docker image uses sqlite:////data/trippy.db).
SQLALCHEMY_DATABASE_URL = os.getenv("TRIPPY_DATABASE_URL", "sqlite:///./trippy.db")

# connect_args={"check_same_thread": False} is needed only for SQLite
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
