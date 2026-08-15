"""Add DAIL-SQL metadata fields to ChatBI Q-SQL.

Revision ID: 20260616_01
Revises: 20260611_01
Create Date: 2026-06-16 16:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_01"
down_revision = "20260611_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ais_chatbi_qsql",
        sa.Column(
            "scope",
            sa.String(length=32),
            nullable=True,
            comment="Q-SQL scope: DATASOURCE/GLOBAL",
        ),
    )
    op.add_column(
        "ais_chatbi_qsql",
        sa.Column(
            "source_dataset",
            sa.String(length=64),
            nullable=True,
            comment="External example source dataset",
        ),
    )
    op.add_column(
        "ais_chatbi_qsql",
        sa.Column(
            "source_db_id",
            sa.String(length=128),
            nullable=True,
            comment="External example original db_id",
        ),
    )
    op.add_column(
        "ais_chatbi_qsql",
        sa.Column(
            "source_sample_id",
            sa.String(length=256),
            nullable=True,
            comment="External example stable id",
        ),
    )
    op.add_column(
        "ais_chatbi_qsql",
        sa.Column(
            "sql_skeleton",
            sa.Text(),
            nullable=True,
            comment="DAIL-SQL SQL skeleton",
        ),
    )
    op.execute("UPDATE ais_chatbi_qsql SET scope = 'DATASOURCE' WHERE scope IS NULL")
    op.alter_column(
        "ais_chatbi_qsql",
        "scope",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.create_index(
        "idx_chatbi_qsql_scope_source",
        "ais_chatbi_qsql",
        ["scope", "source_dataset", "source_db_id"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_qsql_source_sample",
        "ais_chatbi_qsql",
        ["source_dataset", "source_sample_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_chatbi_qsql_source_sample", table_name="ais_chatbi_qsql")
    op.drop_index("idx_chatbi_qsql_scope_source", table_name="ais_chatbi_qsql")
    op.drop_column("ais_chatbi_qsql", "sql_skeleton")
    op.drop_column("ais_chatbi_qsql", "source_sample_id")
    op.drop_column("ais_chatbi_qsql", "source_db_id")
    op.drop_column("ais_chatbi_qsql", "source_dataset")
    op.drop_column("ais_chatbi_qsql", "scope")
