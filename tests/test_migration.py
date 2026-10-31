"""d3a7c1e5f202 (accounts): existing single-user data moves to one owner; other people stay placeholders."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def alembic(db_path: Path, *args: str) -> None:
    env = {**os.environ, "TRIPPY_DATABASE_URL": f"sqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=REPO, env=env, check=True,
                   capture_output=True, text=True)


def test_accounts_migration_assigns_legacy_owner(tmp_path):
    db = tmp_path / "old.db"
    alembic(db, "upgrade", "b4f1e7c2a9d5")
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO users (id, username, email, hashed_password) VALUES (?,?,?,?)", [
        (1, "maya", "maya@example.com", "fakehashed"),
        (2, "ram", "ram@example.com", "fakehashed"),
        (3, "sam", "sam@example.com", "fakehashed"),
    ])
    c.executemany("INSERT INTO trips (id, title, owner_id) VALUES (?,?,?)", [(1, "Tokyo", 2), (2, "Lisbon", 2), (3, "Maya's", 1)])
    c.execute("INSERT INTO trip_participants (user_id, trip_id) VALUES (1, 1)")
    c.execute("INSERT INTO flights (id, trip_id, airline, flight_number) VALUES (1, 3, 'UA', 'UA 1')")
    c.execute("INSERT INTO flights (id, trip_id, airline, flight_number) VALUES (2, NULL, 'DL', 'DL 2')")
    c.execute("INSERT INTO rental_cars (id, rental_company, pickup_location, dropoff_location) VALUES (1, 'Hertz', 'SFO', 'SFO')")
    c.execute("INSERT INTO groups (id, name) VALUES (1, 'Crew')")
    c.execute("INSERT INTO group_members (user_id, group_id) VALUES (1, 1)")
    c.commit()
    c.close()

    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    users = {r[0]: r[1:] for r in c.execute("SELECT id, is_placeholder, legacy_owner FROM users")}
    assert users == {1: (1, 0), 2: (1, 1), 3: (1, 0)}  # nobody has a real password yet; ram owns most trips
    assert dict(c.execute("SELECT id, owner_id FROM flights")) == {1: 1, 2: 2}  # trip owner, else legacy owner
    assert c.execute("SELECT owner_id FROM rental_cars").fetchone() == (2,)
    assert c.execute("SELECT owner_id FROM groups").fetchone() == (2,)
    assert set(c.execute("SELECT user_id FROM group_members WHERE group_id = 1")) == {(1,), (2,)}
    assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
        "lodgings", "password_resets", "trip_invites"}
    c.close()
    alembic(db, "upgrade", "head")  # idempotent
    alembic(db, "downgrade", "b4f1e7c2a9d5")
    alembic(db, "upgrade", "head")
