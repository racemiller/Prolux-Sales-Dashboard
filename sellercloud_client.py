"""
Minimal SellerCloud REST API client.

Handles the one thing that trips people up: SellerCloud does not give you a
static API key. You authenticate with a username + password, get back a
short-lived bearer token (~30-60 min), and send it on every request. This
client fetches that token automatically, refreshes it before it expires, and
re-authenticates once on a 401 in case the token was invalidated early.

Docs: https://developer.sellercloud.com/dev-article/authentication/
"""

import time
import logging

import requests

log = logging.getLogger("sellercloud")


class SellerCloudError(RuntimeError):
    pass


class SellerCloudClient:
    def __init__(self, server_id, username, password, timeout=60):
        # e.g. server_id="cd" -> https://cd.api.sellercloud.com/rest
        self.base_url = f"https://{server_id}.api.sellercloud.com/rest"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self._token = None
        self._token_expires_at = 0.0  # unix epoch seconds

    # ---- auth -------------------------------------------------------------

    def _authenticate(self):
        url = f"{self.base_url}/api/token"
        resp = self.session.post(
            url,
            json={"Username": self.username, "Password": self.password},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise SellerCloudError(
                f"Auth failed ({resp.status_code}). "
                f"Check the username/password and that the user has REST API "
                f"permissions in Delta. Response: {resp.text[:300]}"
            )
        data = resp.json()
        self._token = data["access_token"]
        # Their docs disagree on lifetime (prose says 60m, sample says 1800s).
        # Trust whatever the response reports; refresh 60s early to be safe.
        expires_in = int(data.get("expires_in", 1500))
        self._token_expires_at = time.time() + expires_in - 60
        log.info("Authenticated; token valid ~%ss", expires_in)

    def _ensure_token(self):
        if self._token is None or time.time() >= self._token_expires_at:
            self._authenticate()

    # ---- core request wrapper --------------------------------------------

    def _request(self, method, path, params=None, json_body=None, _auth_retry=True):
        self._ensure_token()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        resp = self.session.request(
            method, url, params=params, json=json_body,
            headers=headers, timeout=self.timeout,
        )

        # Token rejected -> re-auth once and retry.
        if resp.status_code == 401 and _auth_retry:
            log.info("401 received; re-authenticating and retrying once")
            self._authenticate()
            return self._request(method, path, params, json_body, _auth_retry=False)

        # Rate limited -> honor Retry-After (default small backoff) and retry.
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            log.warning("Rate limited; sleeping %ss then retrying", wait)
            time.sleep(wait)
            return self._request(method, path, params, json_body, _auth_retry=_auth_retry)

        if resp.status_code >= 400:
            raise SellerCloudError(
                f"{method} {path} failed ({resp.status_code}) "
                f"params={params} body={resp.text[:300]}"
            )
        return resp.json()

    # ---- endpoints --------------------------------------------------------

    def get_orders_page(self, created_from, created_to, page_number, page_size=50):
        """One page of Get All Orders, filtered by created-on date window."""
        params = {
            "model.createdOnFrom": created_from,
            "model.createdOnTo": created_to,
            "model.pageNumber": page_number,
            "model.pageSize": page_size,
        }
        return self._request("GET", "/api/Orders", params=params)

    def iter_orders(self, created_from, created_to, page_size=50):
        """
        Yield every order in the window, paging until a short/empty page.
        We don't rely on a total-count field so this stays robust even if the
        response shape changes slightly.
        """
        page = 1
        while True:
            data = self.get_orders_page(created_from, created_to, page, page_size)
            items = (data or {}).get("Items") or []
            if not items:
                break
            for item in items:
                yield item
            if len(items) < page_size:
                break
            page += 1
