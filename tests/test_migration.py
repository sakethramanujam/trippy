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


def test_per_owner_external_ids_migration_allows_same_external_id_across_users_and_blocks_same_owner(tmp_path):
    import pytest

    db = tmp_path / "ext.db"
    alembic(db, "upgrade", "c4f8a2d6e913")
    c = sqlite3.connect(db)
    # Simulate an older DB that had a global unique index on rental_cars.external_id and duplicate (owner_id, external_id) rows
    c.execute("DROP INDEX IF EXISTS ix_rental_cars_external_id")
    c.execute("CREATE UNIQUE INDEX ix_rental_cars_external_id ON rental_cars (external_id)")
    c.executemany("INSERT INTO users (id, username, email, hashed_password, is_placeholder, legacy_owner, token_version) VALUES (?,?,?,?,0,0,0)", [
        (1, "ana", "ana@example.com", "$argon2id$v=19$m=65536,t=3,p=4$fake"),
        (2, "ben", "ben@example.com", "$argon2id$v=19$m=65536,t=3,p=4$fake"),
    ])
    c.executemany("INSERT INTO flights (id, owner_id, airline, flight_number, external_id) VALUES (?,?,?,?,?)", [
        (1, 1, "UA", "UA 1", "dup-flight"),
        (2, 1, "UA", "UA 1", "dup-flight"),
    ])
    c.commit()
    c.close()

    alembic(db, "upgrade", "head")
    c = sqlite3.connect(db)
    # Two different users can store the exact same external_id on rental_cars, flights, and lodgings
    c.execute("INSERT INTO rental_cars (owner_id, rental_company, pickup_location, dropoff_location, external_id) VALUES (1, 'Hertz', 'SFO', 'SFO', 'ext-1')")
    c.execute("INSERT INTO rental_cars (owner_id, rental_company, pickup_location, dropoff_location, external_id) VALUES (2, 'Hertz', 'SFO', 'SFO', 'ext-1')")
    c.execute("INSERT INTO flights (owner_id, airline, flight_number, external_id) VALUES (2, 'UA', 'UA 1', 'dup-flight')")
    c.execute("INSERT INTO lodgings (owner_id, name, external_id, time_approx) VALUES (1, 'Hotel A', 'lodg-1', 0)")
    c.execute("INSERT INTO lodgings (owner_id, name, external_id, time_approx) VALUES (2, 'Hotel A', 'lodg-1', 0)")
    c.commit()

    # Same owner with the same external_id is rejected by the per-owner unique index
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO rental_cars (owner_id, rental_company, pickup_location, dropoff_location, external_id) VALUES (1, 'Avis', 'LAX', 'LAX', 'ext-1')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO flights (owner_id, airline, flight_number, external_id) VALUES (1, 'DL', 'DL 2', 'dup-flight')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO lodgings (owner_id, name, external_id, time_approx) VALUES (1, 'Hotel B', 'lodg-1', 0)")
    c.close()

