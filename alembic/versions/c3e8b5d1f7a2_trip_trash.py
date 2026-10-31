"""trips.deleted_at and trips.trash_json (Recently Deleted), and trip_pins (pinned trips)

Revision ID: c3e8b5d1f7a2
Revises: a7d2e9f1c3b5
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8b5d1f7a2"
down_revision: Union[str, None] = "a7d2e9f1c3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("trips")}


def _indexes() -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("trips")}


def upgrade() -> None:
    cols = _cols()  # an app start may already have added them via metadata.create_all on a fresh DB
    # Plain ADD COLUMN (no table copy) so existing rows are untouched.
    if "deleted_at" not in cols:
        op.add_column("trips", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    if "trash_json" not in cols:
        op.add_column("trips", sa.Column("trash_json", sa.Text(), nullable=True))
    if "ix_trips_deleted_at" not in _indexes():
        op.create_index("ix_trips_deleted_at", "trips", ["deleted_at"])
    if not sa.inspect(op.get_bind()).has_table("trip_pins"):
        op.create_table(
            "trip_pins",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_pin_user"),
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("trip_pins"):
        op.drop_table("trip_pins")
    # Trips in Recently Deleted reappear after a downgrade; nothing is lost.
    if "ix_trips_deleted_at" in _indexes():
        op.drop_index("ix_trips_deleted_at", table_name="trips")
    cols = _cols()
    with op.batch_alter_table("trips") as b:
        if "trash_json" in cols:
            b.drop_column("trash_json")
        if "deleted_at" in cols:
            b.drop_column("deleted_at")
