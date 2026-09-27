#!/usr/bin/env python3
"""Small dependency-free Supabase PostgREST client for the scheduled worker."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable


class SupabaseError(RuntimeError):
    pass


class SupabaseRestClient:
    def __init__(self, project_url: str | None = None, secret_key: str | None = None):
        self.project_url = (project_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.secret_key = secret_key or os.environ.get("SUPABASE_SECRET_KEY", "")
        if not self.project_url or not self.secret_key:
            raise SupabaseError("Brakuje SUPABASE_URL albo SUPABASE_SECRET_KEY.")
        self.rest_url = f"{self.project_url}/rest/v1"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Iterable[tuple[str, str]] | None = None,
        payload: Any = None,
        prefer: str = "return=minimal",
    ) -> Any:
        url = f"{self.rest_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(list(params), doseq=True)
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
            "Prefer": prefer,
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise SupabaseError(f"Supabase {method} {path} HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SupabaseError(f"Supabase connection error: {exc}") from exc

    def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Iterable[tuple[str, str]] = (),
        limit: int = 1000,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [("select", columns), ("limit", str(limit)), ("offset", str(offset))]
        if order:
            params.append(("order", order))
        params.extend(filters)
        result = self.request("GET", table, params=params)
        return result if isinstance(result, list) else []

    def select_all(self, table: str, *, columns: str = "*", filters: Iterable[tuple[str, str]] = ()) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.select(table, columns=columns, filters=filters, offset=offset)
            rows.extend(page)
            if len(page) < 1000:
                return rows
            offset += len(page)

    def upsert(self, table: str, rows: list[dict[str, Any]], *, on_conflict: str) -> None:
        if not rows:
            return
        self.request(
            "POST",
            table,
            params=[("on_conflict", on_conflict)],
            payload=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete(self, table: str, *, filters: Iterable[tuple[str, str]]) -> None:
        self.request("DELETE", table, params=list(filters), prefer="return=minimal")
