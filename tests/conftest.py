import os
import sys
import tempfile
from pathlib import Path

import pytest

# app.main runs create_all() on ./trippy.db at import; point that at a scratch dir
# so tests never touch the real database.
_SCRATCH = tempfile.mkdtemp(prefix="trippy-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.chdir(_SCRATCH)
os.environ.setdefault("TRIPPY_JWT_SECRET", "test-secret-not-for-production-0123456789")
for _flag in ("TRIPPY_DEV_AUTH_BYPASS", "TRIPPY_DEV_MODE", "TRIPPY_SEED_DEMO"):
    os.environ.pop(_flag, None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.auth import RateLimiter, get_current_user  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    RateLimiter.reset()
    yield
    RateLimiter.reset()


@pytest.fixture()
def client(db):
    """Signed in without tokens: acts as `client.acting_as` (default: the lowest user id).

    The ledger/split tests predate accounts; they exercise money logic, not auth.
    """
    test_client = TestClient(app)  # not a context manager: skips the demo seed on startup
    test_client.acting_as = None

    def current_user():
        q = db.query(models.User)
        user = q.get(test_client.acting_as) if test_client.acting_as else q.order_by(models.User.id).first()
        assert user is not None, "no users in the test database"
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = current_user
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def api(db):
    """Real authentication: requests need a Bearer token."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def people(db):
    """Owner A plus travelers B, C on one trip."""
    users = [models.User(username=n, email=f"{n.lower()}@t.local", hashed_password="x") for n in ("Ana", "Ben", "Cy")]
    db.add_all(users)
    db.commit()
    trip = models.Trip(title="Tokyo", owner_id=users[0].id)
    trip.participants.extend(users[1:])
    db.add(trip)
    db.commit()
    return {"trip": trip.id, "a": users[0].id, "b": users[1].id, "c": users[2].id}
