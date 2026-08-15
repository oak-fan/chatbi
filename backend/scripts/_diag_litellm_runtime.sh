#!/bin/bash
set -u
cd /home/fan/LAB_ing/chatbi/backend
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "LITELLM_API_BASE=$LITELLM_API_BASE"
echo "DEFAULT_COMPLETION_MODEL=$DEFAULT_COMPLETION_MODEL"
echo "DEFAULT_EMBEDDING_MODEL=$DEFAULT_EMBEDDING_MODEL"
echo "proxy now:"
env | grep -iE '^(http|https|all|no)_proxy=' || echo "(none)"
echo

PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio
import os
import traceback

async def main() -> None:
    from app.llm.runtime import LiteLLMRuntime

    rt = LiteLLMRuntime()
    print("config base:", rt._config.litellm_api_base)
    print("config timeout:", rt._config.litellm_timeout)
    print("config retries:", rt._config.litellm_num_retries)

    print("\n=== litellm acompletion ===")
    try:
        resp = await rt.acompletion(
            model=os.environ.get("DEFAULT_COMPLETION_MODEL", "qwen3.5-4b"),
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        content = resp.choices[0].message.content if getattr(resp, "choices", None) else None
        print("OK", type(resp).__name__, content)
    except Exception as e:
        print("FAIL", type(e).__name__, e)
        traceback.print_exc()

    print("\n=== litellm aembedding ===")
    try:
        resp = await rt.aembedding(
            model=os.environ.get("DEFAULT_EMBEDDING_MODEL", "qwen3-embedding-0.6b"),
            input=["How many singers do we have?"],
        )
        data = getattr(resp, "data", None)
        if data:
            emb = data[0].get("embedding") if isinstance(data[0], dict) else data[0]["embedding"]
            print("OK dims=", len(emb))
        else:
            print("OK resp=", type(resp).__name__)
    except Exception as e:
        print("FAIL", type(e).__name__, e)
        traceback.print_exc()

    print("\n=== 5x rapid acompletion stress ===")
    fails = 0
    for i in range(5):
        try:
            await rt.acompletion(
                model=os.environ.get("DEFAULT_COMPLETION_MODEL", "qwen3.5-4b"),
                messages=[{"role": "user", "content": f"ping{i}"}],
                max_tokens=3,
            )
            print(f"  {i+1}/5 OK")
        except Exception as e:
            fails += 1
            print(f"  {i+1}/5 FAIL {type(e).__name__}: {e}")
    print("fails=", fails)

asyncio.run(main())
PY
