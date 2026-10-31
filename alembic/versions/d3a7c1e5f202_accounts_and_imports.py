"""accounts, invites, password resets, lodgings; legacy data gets one owner

Revision ID: d3a7c1e5f202
Revises: b4f1e7c2a9d5
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a7c1e5f202"
down_revision: Union[str, None] = "b4f1e7c2a9d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _cols(table):
        with op.batch_alter_table(table) as b:
            b.add_column(column)


def upgrade() -> None:
    _add("users", sa.Column("display_name", sa.String(), nullable=True))
    _add("users", sa.Column("home_airport", sa.String(4), nullable=True))
    _add("users", sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add("users", sa.Column("legacy_owner", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    _add("users", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add("flights", sa.Column("owner_id", sa.Integer(), nullable=True))
    _add("flights", sa.Column("external_id", sa.String(), nullable=True))
    _add("rental_cars", sa.Column("owner_id", sa.Integer(), nullable=True))
    _add("groups", sa.Column("owner_id", sa.Integer(), nullable=True))

    if not _has_table("lodgings"):
        op.create_table(
            "lodgings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("address", sa.String(), nullable=True),
            sa.Column("check_in", sa.DateTime(), nullable=True),
            sa.Column("check_out", sa.DateTime(), nullable=True),
            sa.Column("confirmation_number", sa.String(), nullable=True, index=True),
            sa.Column("cost", sa.Float(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("booking_source", sa.String(), nullable=True),
            sa.Column("external_id", sa.String(), nullable=True, index=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
    if not _has_table("password_resets"):
        op.create_table(
            "password_resets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("token_hash", sa.String(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
        )
    if not _has_table("trip_invites"):
        op.create_table(
            "trip_invites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=False, index=True),
            sa.Column("email", sa.String(), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
        )

    # --- Data: everything that existed before accounts belongs to one owner. ---
    bind = op.get_bind()
    has_real = bind.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE hashed_password LIKE '$argon2%'")).scalar()
    if has_real:
        return  # already migrated / accounts in use
    # Nobody has a real password yet, so every existing person is a placeholder.
    bind.execute(sa.text("UPDATE users SET is_placeholder = 1"))
    row = bind.execute(sa.text(
        "SELECT owner_id, COUNT(*) AS n FROM trips WHERE owner_id IS NOT NULL "
        "GROUP BY owner_id ORDER BY n DESC, owner_id ASC LIMIT 1")).first()
    owner_id = row[0] if row else bind.execute(sa.text("SELECT MIN(id) FROM users")).scalar()
    if owner_id is None:
        return  # empty database
    bind.execute(sa.text("UPDATE users SET legacy_owner = 1 WHERE id = :o"), {"o": owner_id})
    bind.execute(sa.text("UPDATE rental_cars SET owner_id = :o WHERE owner_id IS NULL"), {"o": owner_id})
    bind.execute(sa.text(
        "UPDATE flights SET owner_id = COALESCE((SELECT owner_id FROM trips WHERE trips.id = flights.trip_id), :o) "
        "WHERE owner_id IS NULL"), {"o": owner_id})
    bind.execute(sa.text("UPDATE groups SET owner_id = :o WHERE owner_id IS NULL"), {"o": owner_id})
    bind.execute(sa.text("UPDATE trips SET owner_id = :o WHERE owner_id IS NULL"), {"o": owner_id})
    # The owner must be a member of every legacy group so the data stays visible.
    bind.execute(sa.text(
        "INSERT OR IGNORE INTO group_members (user_id, group_id) SELECT :o, id FROM groups"), {"o": owner_id})


def downgrade() -> None:
    for t in ("trip_invites", "password_resets", "lodgings"):
        if _has_table(t):
            op.drop_table(t)
