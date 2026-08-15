"""Normalize ChatBI query log intent column.

Revision ID: 20260524_02
Revises: 20260524_01
Create Date: 2026-05-24 15:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_02"
down_revision = "20260524_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION pg_temp.chatbi_try_parse_jsonb(value text)
            RETURNS jsonb
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RETURN value::jsonb;
            EXCEPTION WHEN others THEN
                RETURN NULL;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH source AS (
                SELECT
                    id,
                    intent AS legacy_intent,
                    btrim(intent) AS trimmed_intent,
                    pg_temp.chatbi_try_parse_jsonb(intent) AS intent_json
                FROM ais_chatbi_query_log
                WHERE intent IS NOT NULL
            ),
            normalized AS (
                SELECT
                    id,
                    legacy_intent,
                    trimmed_intent,
                    CASE
                        WHEN trimmed_intent = '' THEN NULL
                        WHEN trimmed_intent IN ('query', 'clarification', 'unrelated')
                            THEN trimmed_intent
                        ELSE COALESCE(intent_json->>'intent', intent_json->>'choice')
                    END AS raw_intent
                FROM source
            )
            UPDATE ais_chatbi_query_log AS log
            SET
                intent = CASE
                    WHEN normalized.raw_intent IN ('query', 'clarification', 'unrelated')
                        THEN normalized.raw_intent
                    ELSE NULL
                END,
                meta = CASE
                    WHEN normalized.trimmed_intent <> ''
                         AND normalized.trimmed_intent NOT IN (
                             'query',
                             'clarification',
                             'unrelated'
                         )
                        THEN jsonb_set(
                            COALESCE(log.meta, '{}'::jsonb),
                            '{legacy_intent}',
                            to_jsonb(normalized.legacy_intent),
                            true
                        )
                    ELSE log.meta
                END
            FROM normalized
            WHERE log.id = normalized.id;
            """
        )
    )
    op.alter_column(
        "ais_chatbi_query_log",
        "intent",
        existing_type=sa.Text(),
        type_=sa.String(length=64),
        existing_nullable=True,
        comment="意图分类",
        existing_comment="意图 JSON",
        postgresql_using="intent::varchar(64)",
    )


def downgrade() -> None:
    op.alter_column(
        "ais_chatbi_query_log",
        "intent",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        existing_nullable=True,
        comment="意图 JSON",
        existing_comment="意图分类",
    )
    op.execute(
        sa.text(
            """
            UPDATE ais_chatbi_query_log
            SET intent = meta->>'legacy_intent'
            WHERE meta ? 'legacy_intent';
            """
        )
    )
