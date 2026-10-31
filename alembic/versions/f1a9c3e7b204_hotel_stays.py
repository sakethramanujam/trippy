"""hotel stays: brand, place, local zones, room/guests, taxes, loyalty and status on lodgings

Revision ID: f1a9c3e7b204
Revises: e8b2c4d6f013
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9c3e7b204"
down_revision: Union[str, None] = "e8b2c4d6f013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ("brand", sa.String()), ("property_type", sa.String()), ("city", sa.String()), ("country", sa.String()),
    ("lat", sa.Float()), ("lng", sa.Float()), ("check_in_tz", sa.String()), ("check_out_tz", sa.String()),
    ("nights", sa.Integer()), ("room_type", sa.String()), ("rooms", sa.Integer()), ("guests", sa.Integer()),
    ("taxes_fees", sa.Float()), ("loyalty_program", sa.String()), ("loyalty_points", sa.Integer()),
    ("status", sa.String()), ("source_email_ref", sa.String()),
]


def _existing() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("lodgings")}


def upgrade() -> None:
    have = _existing()  # an app start may have created some via metadata.create_all
    todo = [(n, t) for n, t in COLUMNS if n not in have]
    if not todo:
        return
    with op.batch_alter_table("lodgings", schema=None) as batch_op:
        for name, type_ in todo:
            batch_op.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    have = _existing()
    with op.batch_alter_table("lodgings", schema=None) as batch_op:
        for name, _ in reversed(COLUMNS):
            if name in have:
                batch_op.drop_column(name)
