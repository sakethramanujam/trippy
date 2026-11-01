"""drives: Google Maps Timeline drives (per user), matched to trips/journeys/rentals

Revision ID: b9e3d7f1a0c4
Revises: a7c4e2f9b318
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9e3d7f1a0c4"
down_revision: Union[str, None] = "a7c4e2f9b318"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "drives" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "drives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=True),
        sa.Column("journey_id", sa.Integer(), sa.ForeignKey("journeys.id"), nullable=True),
        sa.Column("rental_id", sa.Integer(), sa.ForeignKey("rental_cars.id"), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="google_timeline"),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("start_utc_offset", sa.Integer(), nullable=True),
        sa.Column("end_utc_offset", sa.Integer(), nullable=True),
        sa.Column("distance_miles", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("start_name", sa.String(), nullable=True),
        sa.Column("start_lat", sa.Float(), nullable=True),
        sa.Column("start_lng", sa.Float(), nullable=True),
        sa.Column("end_name", sa.String(), nullable=True),
        sa.Column("end_lat", sa.Float(), nullable=True),
        sa.Column("end_lng", sa.Float(), nullable=True),
        sa.Column("path_json", sa.Text(), nullable=True),
        sa.Column("stops_json", sa.Text(), nullable=True),
        sa.Column("dismissed_rentals_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_drives_id", "drives", ["id"])
    op.create_index("ix_drives_owner_id", "drives", ["owner_id"])
    op.create_index("ix_drives_trip_id", "drives", ["trip_id"])
    op.create_index("ix_drives_journey_id", "drives", ["journey_id"])
    op.create_index("ix_drives_rental_id", "drives", ["rental_id"])
    op.create_index("ix_drives_start_time", "drives", ["start_time"])
    op.create_index("uq_drives_owner_external", "drives", ["owner_id", "external_id"], unique=True)


def downgrade() -> None:
    op.drop_table("drives")
