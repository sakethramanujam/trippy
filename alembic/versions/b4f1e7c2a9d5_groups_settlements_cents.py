"""groups_settlements_cents

Shared-expense upgrade:
- exact cents on expenses and splits (backfilled from the float columns)
- split_mode / per-person share value so edits can re-split
- groups (named sets of people) that trips and standalone expenses can belong to
- settlements: recorded payments that net out balances without deleting history

Revision ID: b4f1e7c2a9d5
Revises: 7c2e9d4a1b30
Create Date: 2026-10-30 09:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4f1e7c2a9d5'
down_revision: Union[str, Sequence[str], None] = '7c2e9d4a1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # The app calls create_all() at import, so new tables may already exist.
    if not _has_table('groups'):
        op.create_table(
            'groups',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_groups_id', 'groups', ['id'])
    if not _has_table('group_members'):
        op.create_table(
            'group_members',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), primary_key=True),
        )
    if not _has_table('settlements'):
        op.create_table(
            'settlements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('to_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('amount_cents', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=3), nullable=True),
            sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=True),
            sa.Column('note', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_settlements_id', 'settlements', ['id'])

    if 'group_id' not in _columns('trips'):
        with op.batch_alter_table('trips', schema=None) as batch_op:
            batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_trips_group_id', 'groups', ['group_id'], ['id'])

    cols = _columns('expenses')
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        if 'amount_cents' not in cols:
            batch_op.add_column(sa.Column('amount_cents', sa.Integer(), nullable=True))
        if 'split_mode' not in cols:
            batch_op.add_column(sa.Column('split_mode', sa.String(), nullable=True))
        if 'group_id' not in cols:
            batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_expenses_group_id', 'groups', ['group_id'], ['id'])

    cols = _columns('expense_splits')
    with op.batch_alter_table('expense_splits', schema=None) as batch_op:
        if 'amount_cents' not in cols:
            batch_op.add_column(sa.Column('amount_cents', sa.Integer(), nullable=True))
        if 'share' not in cols:
            batch_op.add_column(sa.Column('share', sa.Float(), nullable=True))

    op.execute("UPDATE expenses SET amount_cents = CAST(ROUND(amount * 100) AS INTEGER) WHERE amount_cents IS NULL AND amount IS NOT NULL")
    op.execute("UPDATE expenses SET split_mode = 'equal' WHERE split_mode IS NULL")
    op.execute("UPDATE expense_splits SET amount_cents = CAST(ROUND(amount_owed * 100) AS INTEGER) WHERE amount_cents IS NULL AND amount_owed IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table('expense_splits', schema=None) as batch_op:
        batch_op.drop_column('share')
        batch_op.drop_column('amount_cents')
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_expenses_group_id', type_='foreignkey')
        batch_op.drop_column('group_id')
        batch_op.drop_column('split_mode')
        batch_op.drop_column('amount_cents')
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trips_group_id', type_='foreignkey')
        batch_op.drop_column('group_id')
    op.drop_index('ix_settlements_id', table_name='settlements')
    op.drop_table('settlements')
    op.drop_table('group_members')
    op.drop_index('ix_groups_id', table_name='groups')
    op.drop_table('groups')
