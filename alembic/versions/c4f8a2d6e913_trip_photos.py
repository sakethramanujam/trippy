"""trip_photos: per-user trip photo thumbnails (full photos stay on the device)

Revision ID: c4f8a2d6e913
Revises: b9e3d7f1a0c4
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f8a2d6e913"
down_revision: Union[str, None] = "b9e3d7f1a0c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "trip_photos" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "trip_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("thumb", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trip_photos_id", "trip_photos", ["id"])
    op.create_index("ix_trip_photos_trip_id", "trip_photos", ["trip_id"])
    op.create_index("ix_trip_photos_user_id", "trip_photos", ["user_id"])
    op.create_index("ix_trip_photos_taken_at", "trip_photos", ["taken_at"])
    op.create_index("uq_trip_photos_asset", "trip_photos", ["user_id", "trip_id", "device_id", "asset_id"], unique=True)


def downgrade() -> None:
    op.drop_table("trip_photos")
