"""放宽 benchmark 聚合指标 metric_value 精度以容纳毫秒/ token 均值。

Revision ID: 20260611_01
Revises: 20260610_01
Create Date: 2026-06-11 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_01"
down_revision = "20260610_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ais_chatbi_benchmark_metric_summary",
        "metric_value",
        existing_type=sa.Numeric(8, 6),
        type_=sa.Numeric(16, 4),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "ais_chatbi_benchmark_metric_summary",
        "metric_value",
        existing_type=sa.Numeric(16, 4),
        type_=sa.Numeric(8, 6),
        existing_nullable=False,
    )
