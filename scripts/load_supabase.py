#!/usr/bin/env python3
"""Bulk-load data/*.json into Supabase through the PostgREST API.

Why not the MCP server: pushing 24.109 rows as SQL literals through an MCP
tool means dozens of very large calls. This does the same work in ~25 HTTP
requests. Schema changes and verification still go through the MCP server.

Idempotent: uses Prefer: resolution=merge-duplicates, so re-running upserts on
the primary key instead of failing. Tables load in FK order.

Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from .env.local (or the
environment). The service_role key bypasses RLS, which is what a loader needs
and exactly why it must never reach the frontend.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BATCH = 1000


def ssl_context() -> ssl.SSLContext:
    """python.org builds on macOS ship no root certificates and fail every
    HTTPS call with CERTIFICATE_VERIFY_FAILED. Use certifi's bundle when it is
    installed, otherwise fall back to the system defaults."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = ssl_context()

# (file, table) in foreign-key order: models reference brands, skus reference models.
TABLES = [
    ("brands.json", "brands"),
    ("models.json", "models"),
    ("skus.json", "skus"),
]


def load_env() -> tuple[str, str]:
    env_file = ROOT / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        sys.exit(
            "Missing credentials. Create .env.local with:\n"
            "  SUPABASE_URL=https://<project-ref>.supabase.co\n"
            "  SUPABASE_SERVICE_ROLE_KEY=<service_role key from the dashboard>"
        )
    return url, key


def post(url: str, key: str, table: str, rows: list[dict]) -> None:
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/rest/v1/{table}",
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Upsert on the primary key, and don't echo the rows back.
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120, context=SSL) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        sys.exit(f"\n{table}: HTTP {exc.code} {exc.reason}\n{detail}")
    except urllib.error.URLError as exc:
        sys.exit(f"\n{table}: could not reach {url} ({exc.reason})")


def main() -> int:
    url, key = load_env()
    print(f"Loading into {url}")

    for filename, table in TABLES:
        path = DATA / filename
        if not path.exists():
            sys.exit(f"{path.relative_to(ROOT)} missing. Run scripts/extract_dataset.py first.")

        rows = json.loads(path.read_text(encoding="utf-8"))
        total = len(rows)
        for start in range(0, total, BATCH):
            chunk = rows[start:start + BATCH]
            post(url, key, table, chunk)
            done = min(start + BATCH, total)
            print(f"\r  {table:<8} {done:>6,}/{total:,}", end="", flush=True)
        print(f"\r  {table:<8} {total:>6,}/{total:,}  done")

    print("Load complete. Verify with scripts/verify.sql through the Supabase MCP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
