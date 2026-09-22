#!/usr/bin/env python3
"""Minimal Supabase/PostgREST client shared by the loader and the scraper.

Factored out of load_supabase.py so both use the same credential handling, SSL
context and batching rather than two drifting copies.

Uses only the standard library plus certifi, so there is nothing to install in
CI beyond what the repo already needs.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCH = 1000


def _ssl_context() -> ssl.SSLContext:
    """python.org builds on macOS ship no root certificates and fail every HTTPS
    call with CERTIFICATE_VERIFY_FAILED. Use certifi's bundle when present."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = _ssl_context()


def load_env(require: tuple[str, ...] = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")) -> dict:
    """Read .env.local into os.environ (without overriding real env vars) and
    return the requested keys. CI supplies them as secrets, so a missing file is
    not an error on its own."""
    env_file = ROOT / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    out = {k: os.environ.get(k, "").rstrip("/") if k.endswith("URL")
           else os.environ.get(k, "") for k in require}
    missing = [k for k, v in out.items() if not v]
    if missing:
        sys.exit("Missing credentials: " + ", ".join(missing) +
                 "\nSet them in .env.local or the environment.")
    return out


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None):
        if url and key:
            self.url, self.key = url.rstrip("/"), key
        else:
            env = load_env()
            self.url = env["SUPABASE_URL"]
            self.key = env["SUPABASE_SERVICE_ROLE_KEY"]

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
             "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def _request(self, method: str, path: str, *, body=None, headers=None, timeout=120):
        data = json.dumps(body, ensure_ascii=False, default=str).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}/rest/v1/{path}", data=data,
                                     method=method, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:600]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code} {e.reason}\n{detail}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"{method} {path} -> cannot reach {self.url} ({e.reason})") from None

    def select(self, table: str, **params) -> list[dict]:
        """Paginates past PostgREST's 1.000-row response cap automatically.

        An explicit `limit` is honoured and stops the paging — otherwise a
        caller asking for 1 row would silently get the whole table."""
        want = params.pop("limit", None)
        out, offset = [], 0
        while True:
            q = dict(params)
            q.setdefault("select", "*")
            q["limit"] = BATCH if want is None else min(BATCH, want - len(out))
            q["offset"] = offset
            page = self._request("GET", f"{table}?{urllib.parse.urlencode(q)}") or []
            out.extend(page)
            if len(page) < BATCH or (want is not None and len(out) >= want):
                return out
            offset += BATCH

    def insert(self, table: str, rows: list[dict], *, returning: bool = False) -> list[dict]:
        """Plain insert — for append-only tables where upserting would be wrong."""
        out = []
        for i in range(0, len(rows), BATCH):
            prefer = "return=representation" if returning else "return=minimal"
            got = self._request("POST", table, body=rows[i:i + BATCH],
                                headers={"Prefer": prefer})
            if returning and got:
                out.extend(got)
        return out

    def upsert(self, table: str, rows: list[dict], *, on_conflict: str | None = None,
               returning: bool = False) -> list[dict]:
        out = []
        path = f"{table}?on_conflict={on_conflict}" if on_conflict else table
        prefer = "resolution=merge-duplicates," + ("return=representation" if returning else "return=minimal")
        for i in range(0, len(rows), BATCH):
            got = self._request("POST", path, body=rows[i:i + BATCH],
                                headers={"Prefer": prefer})
            if returning and got:
                out.extend(got)
        return out

    def rpc(self, fn: str, **args):
        """Call a Postgres function. Used to rebuild the public comparison
        table, so that logic lives in SQL rather than being duplicated here."""
        return self._request("POST", f"rpc/{fn}", body=args or {})

    def update(self, table: str, values: dict, **filters) -> None:
        q = urllib.parse.urlencode(filters)
        self._request("PATCH", f"{table}?{q}", body=values,
                      headers={"Prefer": "return=minimal"})
