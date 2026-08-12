"""
Minimal Jotform API client. Read-only: list submissions for a form, with
optional incremental filtering by created_at. Auth is just an API key.

EU/HIPAA accounts use a different base_url (https://eu-api.jotform.com).
"""

import json
import time
import logging

import requests

log = logging.getLogger("jotform")


class JotformError(RuntimeError):
    pass


class JotformClient:
    def __init__(self, api_key, base_url="https://api.jotform.com", timeout=60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path, params=None):
        params = dict(params or {})
        params["apiKey"] = self.api_key
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "10"))
            log.warning("Rate limited; sleeping %ss", wait)
            time.sleep(wait)
            return self._get(path, params)
        if resp.status_code >= 400:
            raise JotformError(f"GET {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def iter_submissions(self, form_id, since=None, page_size=1000):
        """
        Yield submissions for a form, paging via limit/offset. `since` is a
        'YYYY-MM-DD HH:MM:SS' string; only submissions created after it come back.
        """
        offset = 0
        while True:
            params = {"limit": page_size, "offset": offset, "orderby": "created_at"}
            if since:
                params["filter"] = json.dumps({"created_at:gt": since})
            data = self._get(f"/form/{form_id}/submissions", params)
            content = data.get("content") or []
            if not content:
                break
            for sub in content:
                yield sub
            if len(content) < page_size:
                break
            offset += page_size
