#!/bin/bash
set -u
cd /home/fan/LAB_ing/chatbi/backend

echo "=== proxy env ==="
env | grep -iE '^(http|https|all|no)_proxy=' || echo "(no proxy env vars)"
echo

echo "=== profile proxy hints ==="
grep -nHiE 'proxy' ~/.bashrc ~/.profile ~/.zshrc ~/.bash_profile 2>/dev/null | head -40 || true
echo

echo "=== DNS ==="
getent hosts litellm.i.hitices.cn || true
echo

echo "=== curl noproxy ==="
if curl -sS -o /tmp/llm_noproxy.json -w "http_code=%{http_code} time=%{time_total}\n" --connect-timeout 15 --noproxy '*' \
  -X POST "https://litellm.i.hitices.cn/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-6hLtyhrWzSCXpXdOrd8oKQ" \
  -d '{"model":"qwen3.5-4b","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'; then
  echo "body:"; head -c 300 /tmp/llm_noproxy.json; echo
else
  echo "curl_noproxy_failed=$?"
fi
echo

echo "=== curl default env ==="
if curl -sS -o /tmp/llm_proxy.json -w "http_code=%{http_code} time=%{time_total}\n" --connect-timeout 15 \
  -X POST "https://litellm.i.hitices.cn/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-6hLtyhrWzSCXpXdOrd8oKQ" \
  -d '{"model":"qwen3.5-4b","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'; then
  echo "body:"; head -c 300 /tmp/llm_proxy.json; echo
else
  echo "curl_default_failed=$?"
fi
echo

echo "=== python httpx/aiohttp via project venv ==="
PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio
import os

print("proxy in os.environ:")
found = False
for k, v in sorted(os.environ.items()):
    if "proxy" in k.lower():
        print(f"  {k}={v}")
        found = True
if not found:
    print("  (none)")

url = "https://litellm.i.hitices.cn/chat/completions"
headers = {
    "Authorization": "Bearer sk-6hLtyhrWzSCXpXdOrd8oKQ",
    "Content-Type": "application/json",
}
payload = {
    "model": "qwen3.5-4b",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 5,
}


async def main() -> None:
    import httpx

    print("\n[httpx] default (respects env proxy):")
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(url, headers=headers, json=payload)
            print("  status", r.status_code, "len", len(r.text))
            print("  body", r.text[:200])
    except Exception as e:
        print("  FAIL", type(e).__name__, e)

    print("\n[httpx] trust_env=False (no proxy):")
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as c:
            r = await c.post(url, headers=headers, json=payload)
            print("  status", r.status_code, "len", len(r.text))
            print("  body", r.text[:200])
    except Exception as e:
        print("  FAIL", type(e).__name__, e)

    print("\n[aiohttp] default:")
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                text = await r.text()
                print("  status", r.status, "len", len(text))
                print("  body", text[:200])
    except Exception as e:
        print("  FAIL", type(e).__name__, e)

    print("\n[aiohttp] trust_env=False:")
    try:
        import aiohttp

        async with aiohttp.ClientSession(trust_env=False) as s:
            async with s.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                text = await r.text()
                print("  status", r.status, "len", len(text))
                print("  body", text[:200])
    except Exception as e:
        print("  FAIL", type(e).__name__, e)


asyncio.run(main())
PY
