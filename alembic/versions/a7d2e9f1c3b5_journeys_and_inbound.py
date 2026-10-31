"""journeys (linked trips), dismissed journey suggestions, and forwarded-email inbox

Revision ID: a7d2e9f1c3b5
Revises: f1a9c3e7b204
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2e9f1c3b5"
down_revision: Union[str, None] = "f1a9c3e7b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    return sa.inspect(op.get_bind())


def _cols(table: str) -> set[str]:
    return {c["name"] for c in _insp().get_columns(table)}


def upgrade() -> None:
    tables = set(_insp().get_table_names())  # an app start may have created some via metadata.create_all
    if "journeys" not in tables:
        op.create_table(
            "journeys",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("cover_photo", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_journeys_id", "journeys", ["id"])
        op.create_index("ix_journeys_owner_id", "journeys", ["owner_id"])
    if "dismissed_suggestions" not in tables:
        op.create_table(
            "dismissed_suggestions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trip_key", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "trip_key", name="uq_dismissed_suggestion"),
        )
        op.create_index("ix_dismissed_suggestions_user_id", "dismissed_suggestions", ["user_id"])
    if "inbound_emails" not in tables:
        op.create_table(
            "inbound_emails",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("message_id", sa.String(), nullable=False),
            sa.Column("sender", sa.String(), nullable=True),
            sa.Column("subject", sa.String(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("routed_by", sa.String(), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("raw", sa.LargeBinary(), nullable=True),
            sa.Column("seen", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_inbound_emails_user_id", "inbound_emails", ["user_id"])
        op.create_index("ix_inbound_emails_message_id", "inbound_emails", ["message_id"])
        op.create_index("uq_inbound_emails_user_message", "inbound_emails", ["user_id", "message_id"], unique=True)

    have = _cols("trips")
    todo = [c for c in ("journey_id", "journey_position") if c not in have]
    if todo:
        with op.batch_alter_table("trips", schema=None) as b:
            if "journey_id" in todo:
                b.add_column(sa.Column("journey_id", sa.Integer(), nullable=True))
                b.create_index("ix_trips_journey_id", ["journey_id"])
                b.create_foreign_key("fk_trips_journey_id", "journeys", ["journey_id"], ["id"])
            if "journey_position" in todo:
                b.add_column(sa.Column("journey_position", sa.Integer(), nullable=True))
    if "inbound_token" not in _cols("users"):
        with op.batch_alter_table("users", schema=None) as b:
            b.add_column(sa.Column("inbound_token", sa.String(), nullable=True))
            b.create_index("ix_users_inbound_token", ["inbound_token"], unique=True)


def downgrade() -> None:
    insp = _insp()
    if "inbound_token" in _cols("users"):
        idx = {i["name"] for i in insp.get_indexes("users")}
        with op.batch_alter_table("users", schema=None) as b:
            if "ix_users_inbound_token" in idx:
                b.drop_index("ix_users_inbound_token")
            b.drop_column("inbound_token")
    have = _cols("trips")
    if have & {"journey_id", "journey_position"}:
        idx = {i["name"] for i in insp.get_indexes("trips")}
        fks = [f["name"] for f in insp.get_foreign_keys("trips") if f["referred_table"] == "journeys"]
        with op.batch_alter_table("trips", schema=None) as b:
            for name in fks:
                if name:
                    b.drop_constraint(name, type_="foreignkey")
            if "ix_trips_journey_id" in idx:
                b.drop_index("ix_trips_journey_id")
            for c in ("journey_position", "journey_id"):
                if c in have:
                    b.drop_column(c)
    tables = set(insp.get_table_names())
    for t in ("inbound_emails", "dismissed_suggestions", "journeys"):
        if t in tables:
            op.drop_table(t)
