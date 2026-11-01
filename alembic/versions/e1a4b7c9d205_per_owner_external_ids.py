"""per_owner_external_ids: unique (owner_id, external_id) on flights, rental_cars, and lodgings

Revision ID: e1a4b7c9d205
Revises: c4f8a2d6e913
Create Date: 2026-11-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a4b7c9d205"
down_revision: Union[str, None] = "c4f8a2d6e913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    ("flights", "uq_flights_owner_external"),
    ("rental_cars", "uq_rental_cars_owner_external"),
    ("lodgings", "uq_lodgings_owner_external"),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, uq_name in _TABLES:
        if not insp.has_table(table):
            continue
        # Ensure any legacy rows with NULL owner_id get their trip's owner_id where available.
        bind.execute(sa.text(
            f"UPDATE {table} SET owner_id = ("
            f"SELECT owner_id FROM trips WHERE trips.id = {table}.trip_id"
            f") WHERE owner_id IS NULL AND trip_id IS NOT NULL"
        ))
        # Deduplicate any pre-existing duplicate (owner_id, external_id) pairs by clearing external_id on older rows.
        bind.execute(sa.text(
            f"UPDATE {table} SET external_id = NULL "
            f"WHERE external_id IS NOT NULL AND id NOT IN ("
            f"SELECT MAX(id) FROM {table} WHERE external_id IS NOT NULL GROUP BY owner_id, external_id"
            f")"
        ))
        indexes = {ix["name"]: ix for ix in insp.get_indexes(table)}
        unique_constraints = {uc["name"] for uc in insp.get_unique_constraints(table) if uc.get("name")}
        with op.batch_alter_table(table, schema=None) as batch_op:
            # Drop any legacy global unique index on external_id alone.
            for ix_name, ix in indexes.items():
                if ix.get("unique") and ix.get("column_names") == ["external_id"]:
                    batch_op.drop_index(ix_name)
            for uc_name in unique_constraints:
                if "external_id" in uc_name and uc_name != uq_name:
                    batch_op.drop_constraint(uc_name, type_="unique")
            if f"ix_{table}_external_id" not in indexes or indexes[f"ix_{table}_external_id"].get("unique"):
                batch_op.create_index(f"ix_{table}_external_id", ["external_id"], unique=False)
            if uq_name not in indexes:
                batch_op.create_index(uq_name, ["owner_id", "external_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, uq_name in _TABLES:
        if not insp.has_table(table):
            continue
        indexes = {ix["name"] for ix in insp.get_indexes(table)}
        if uq_name in indexes:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.drop_index(uq_name)
