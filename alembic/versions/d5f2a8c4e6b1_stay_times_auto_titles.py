"""lodgings.time_approx (date-only stays) and trips.title_auto (route titles)

Data fixes, both reversible by `alembic downgrade c3e8b5d1f7a2`:
- A stay whose check-in AND check-out are both exactly midnight came from a date-only source
  (a calendar all-day event). It gets the usual 3 PM / 11 AM and time_approx = 1, so the app
  shows "Check-in ~3 PM" instead of 12:00 AM. Downgrade puts those rows back to midnight.
- Trips titled "… (auto)", "… (flights)" or "… (email)" get title_auto = 1, so their title can
  follow the full route. Every other title was set by a person and stays as is.

Revision ID: d5f2a8c4e6b1
Revises: c3e8b5d1f7a2
Create Date: 2026-10-30
"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5f2a8c4e6b1"
down_revision: Union[str, None] = "c3e8b5d1f7a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_IN_HOUR, CHECK_OUT_HOUR = 15, 11


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


def _midnight(d) -> bool:
    return d is not None and (d.hour, d.minute, d.second, d.microsecond) == (0, 0, 0, 0)


def upgrade() -> None:
    bind = op.get_bind()
    if "time_approx" not in _cols("lodgings"):
        op.add_column("lodgings", sa.Column("time_approx", sa.Boolean(), nullable=False, server_default="0"))
    if "title_auto" not in _cols("trips"):
        op.add_column("trips", sa.Column("title_auto", sa.Boolean(), nullable=False, server_default="0"))

    lodgings = sa.table("lodgings", sa.column("id", sa.Integer), sa.column("check_in", sa.DateTime),
                        sa.column("check_out", sa.DateTime), sa.column("time_approx", sa.Boolean))
    for row in bind.execute(sa.select(lodgings.c.id, lodgings.c.check_in, lodgings.c.check_out,
                                      lodgings.c.time_approx)).all():
        cin, cout = _dt(row.check_in), _dt(row.check_out)
        if row.time_approx or not _midnight(cin) or not (cout is None or _midnight(cout)):
            continue
        bind.execute(lodgings.update().where(lodgings.c.id == row.id).values(
            check_in=cin.replace(hour=CHECK_IN_HOUR),
            check_out=cout.replace(hour=CHECK_OUT_HOUR) if cout else None,
            time_approx=True))

    trips = sa.table("trips", sa.column("id", sa.Integer), sa.column("title", sa.String),
                     sa.column("title_auto", sa.Boolean))
    for suffix in ("(auto)", "(flights)", "(email)"):
        bind.execute(trips.update().where(trips.c.title.like(f"%{suffix}")).values(title_auto=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "time_approx" in _cols("lodgings"):
        lodgings = sa.table("lodgings", sa.column("id", sa.Integer), sa.column("check_in", sa.DateTime),
                            sa.column("check_out", sa.DateTime), sa.column("time_approx", sa.Boolean))
        for row in bind.execute(sa.select(lodgings.c.id, lodgings.c.check_in, lodgings.c.check_out)
                                .where(lodgings.c.time_approx == True)).all():  # noqa: E712
            cin, cout = _dt(row.check_in), _dt(row.check_out)
            bind.execute(lodgings.update().where(lodgings.c.id == row.id).values(
                check_in=cin.replace(hour=0, minute=0, second=0, microsecond=0) if cin else None,
                check_out=cout.replace(hour=0, minute=0, second=0, microsecond=0) if cout else None))
        with op.batch_alter_table("lodgings") as b:
            b.drop_column("time_approx")
    if "title_auto" in _cols("trips"):
        with op.batch_alter_table("trips") as b:
            b.drop_column("title_auto")
