"""trip_invites.code_hash / code_expires_at: one-time invite codes for claiming a traveler

Signing up as (or joining as) a placeholder traveler now needs a one-time code that the
inviter shares out of band, or an allowlisted email. Codes are stored hashed.

Revision ID: a7c4e2f9b318
Revises: d5f2a8c4e6b1
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c4e2f9b318"
down_revision: Union[str, None] = "d5f2a8c4e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = _cols("trip_invites")
    if "code_hash" not in cols:
        op.add_column("trip_invites", sa.Column("code_hash", sa.String(), nullable=True))
        op.create_index("ix_trip_invites_code_hash", "trip_invites", ["code_hash"])
    if "code_expires_at" not in cols:
        op.add_column("trip_invites", sa.Column("code_expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_invites") as b:
        b.drop_index("ix_trip_invites_code_hash")
        b.drop_column("code_expires_at")
        b.drop_column("code_hash")
