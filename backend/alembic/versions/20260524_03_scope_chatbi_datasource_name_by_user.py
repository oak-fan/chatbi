"""Scope ChatBI datasource name uniqueness by user.

Revision ID: 20260524_03
Revises: 20260524_02
Create Date: 2026-05-24 20:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_03"
down_revision = "20260524_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_ais_chatbi_datasource_name_active", table_name="ais_chatbi_datasource")
    op.create_index(
        "uq_ais_chatbi_datasource_owner_name_active",
        "ais_chatbi_datasource",
        ["created_by", "name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ais_chatbi_datasource_owner_name_active",
        table_name="ais_chatbi_datasource",
    )
    op.create_index(
        "uq_ais_chatbi_datasource_name_active",
        "ais_chatbi_datasource",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
