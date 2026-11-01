"""Add terminal, gate, and notes columns to flights

Revision ID: f2b6c8d4e109
Revises: e1a4b7c9d205
Create Date: 2026-04-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b6c8d4e109"
down_revision: Union[str, Sequence[str], None] = "e1a4b7c9d205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = _cols("flights")
    if "terminal" not in cols:
        op.add_column("flights", sa.Column("terminal", sa.String(), nullable=True))
    if "gate" not in cols:
        op.add_column("flights", sa.Column("gate", sa.String(), nullable=True))
    if "notes" not in cols:
        op.add_column("flights", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    cols = _cols("flights")
    with op.batch_alter_table("flights") as batch_op:
        if "notes" in cols:
            batch_op.drop_column("notes")
        if "gate" in cols:
            batch_op.drop_column("gate")
        if "terminal" in cols:
            batch_op.drop_column("terminal")
