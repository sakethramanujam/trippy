"""rental_tracker_fields

Standalone rental tracker: vehicle make/year/photo, station codes, cities and
coordinates, approximate-date flag and an external id for idempotent imports.

Revision ID: 7c2e9d4a1b30
Revises: 40b8fa012da1
Create Date: 2026-10-29 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e9d4a1b30'
down_revision: Union[str, Sequence[str], None] = '40b8fa012da1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STRING_COLUMNS = [
    'agreement_number', 'vehicle_make', 'vehicle_color', 'license_plate', 'photo_url',
    'pickup_code', 'pickup_city', 'dropoff_code', 'dropoff_city',
]
_FLOAT_COLUMNS = ['pickup_lat', 'pickup_lng', 'dropoff_lat', 'dropoff_lng']


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('rental_cars', schema=None) as batch_op:
        batch_op.add_column(sa.Column('external_id', sa.String(), nullable=True))
        for name in _STRING_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(), nullable=True))
        batch_op.add_column(sa.Column('vehicle_year', sa.Integer(), nullable=True))
        for name in _FLOAT_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('date_approx', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_rental_cars_external_id'), ['external_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('rental_cars', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rental_cars_external_id'))
        batch_op.drop_column('notes')
        batch_op.drop_column('date_approx')
        for name in reversed(_FLOAT_COLUMNS):
            batch_op.drop_column(name)
        batch_op.drop_column('vehicle_year')
        for name in reversed(_STRING_COLUMNS):
            batch_op.drop_column(name)
        batch_op.drop_column('external_id')
