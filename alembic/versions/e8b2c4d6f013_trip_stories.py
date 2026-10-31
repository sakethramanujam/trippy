"""trip stories: per-user edits to a trip's generated story

Revision ID: e8b2c4d6f013
Revises: d3a7c1e5f202
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b2c4d6f013"
down_revision: Union[str, None] = "d3a7c1e5f202"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("trip_stories"):
        return  # created by metadata.create_all on an app start before this migration ran
    op.create_table(
        "trip_stories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("subtitle", sa.String(), nullable=True),
        sa.Column("theme", sa.String(), nullable=True),
        sa.Column("cover_photo", sa.String(), nullable=True),
        sa.Column("order_json", sa.Text(), nullable=True),
        sa.Column("items_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_story_user"),
    )
    op.create_index("ix_trip_stories_trip_id", "trip_stories", ["trip_id"])
    op.create_index("ix_trip_stories_user_id", "trip_stories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_trip_stories_user_id", table_name="trip_stories")
    op.drop_index("ix_trip_stories_trip_id", table_name="trip_stories")
    op.drop_table("trip_stories")
