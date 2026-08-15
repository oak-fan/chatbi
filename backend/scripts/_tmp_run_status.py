import asyncio
from pathlib import Path

import asyncpg


async def main() -> None:
    url = None
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        print("no DATABASE_URL")
        return
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        """
        SELECT id, status, processed_count, total_count, created_at
        FROM ais_chatbi_benchmark_run
        ORDER BY id DESC
        LIMIT 5
        """
    )
    for row in rows:
        item = dict(row)
        if item["id"] == rows[0]["id"] and item["processed_count"]:
            acc = await conn.fetchval(
                """
                SELECT AVG(execution_accuracy)
                FROM ais_chatbi_benchmark_case_result
                WHERE run_id = $1 AND status = 'SUCCESS'
                """,
                item["id"],
            )
            item["partial_ex"] = round(float(acc or 0), 4)
        print(item)
    await conn.close()


asyncio.run(main())
