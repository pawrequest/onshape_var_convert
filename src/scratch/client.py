"""Thin Onshape REST client (API-key Basic auth)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://cad.onshape.com"
DEFAULT_API_VERSION = "v10"
_HEADERS = {
    "Accept": "application/json;charset=UTF-8; qs=0.09",
    "Content-Type": "application/json;charset=UTF-8; qs=0.09",
}


class OnshapeError(RuntimeError):
    pass

PROJECT_ROOT = Path(__file__).parent.parent.parent
def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class OnshapeClient:
    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        access = access_key or os.environ.get("ONSHAPE_ACCESS_KEY")
        secret = secret_key or os.environ.get("ONSHAPE_SECRET_KEY")
        if not access or not secret:
            raise OnshapeError("ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY must be set (env or .env).")
        base = (base_url or os.environ.get("ONSHAPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        version = api_version or os.environ.get("ONSHAPE_API_VERSION") or DEFAULT_API_VERSION
        self._max_retries = max_retries
        self._http = httpx.Client(
            base_url=f"{base}/api/{version}",
            auth=(access, secret),
            headers=_HEADERS,
            timeout=30,
            transport=transport,
        )

    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        for attempt in range(self._max_retries + 1):
            response = self._http.request(method, path, json=json, params=params)
            if response.status_code == 429 and attempt < self._max_retries:
                time.sleep(float(response.headers.get("Retry-After", 2 ** attempt)))
                continue
            break
        if response.is_error:
            raise OnshapeError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else {}

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, json=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)
