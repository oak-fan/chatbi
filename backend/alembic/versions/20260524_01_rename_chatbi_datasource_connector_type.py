"""Rename ChatBI datasource type column.

Revision ID: 20260524_01
Revises: 20260520_02
Create Date: 2026-05-24 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_01"
down_revision = "20260520_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_chatbi_datasource_type", table_name="ais_chatbi_datasource")
    op.alter_column(
        "ais_chatbi_datasource",
        "type",
        new_column_name="connector_type",
        existing_type=sa.String(length=32),
    )
    op.create_index(
        "idx_chatbi_datasource_connector_type",
        "ais_chatbi_datasource",
        ["connector_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_chatbi_datasource_connector_type",
        table_name="ais_chatbi_datasource",
    )
    op.alter_column(
        "ais_chatbi_datasource",
        "connector_type",
        new_column_name="type",
        existing_type=sa.String(length=32),
    )
    op.create_index(
        "idx_chatbi_datasource_type",
        "ais_chatbi_datasource",
        ["type"],
        unique=False,
    )
