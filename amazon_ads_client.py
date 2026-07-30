"""
Amazon Ads API client. Same shape as the SellerCloud client: a long-lived
refresh token mints short-lived access tokens, refreshed automatically.

Regions: NA covers US/CA/MX (that's you). EU / FE exist if you ever expand.
"""

import time
import logging

import requests

log = logging.getLogger("amazon_ads")

TOKEN_ENDPOINTS = {
    "NA": "https://api.amazon.com/auth/o2/token",
    "EU": "https://api.amazon.co.uk/auth/o2/token",
    "FE": "https://api.amazon.co.jp/auth/o2/token",
}

API_ENDPOINTS = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}


class AmazonAdsError(RuntimeError):
    pass


class AmazonAdsClient:
    def __init__(self, client_id, client_secret, refresh_token, region="NA", timeout=60):
        if region not in API_ENDPOINTS:
            raise ValueError(f"region must be one of {list(API_ENDPOINTS)}")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.region = region
        self.token_url = TOKEN_ENDPOINTS[region]
        self.base_url = API_ENDPOINTS[region]
        self.timeout = timeout
        self.session = requests.Session()
        self._access_token = None
        self._expires_at = 0.0

    def _refresh(self):
        resp = self.session.post(
            self.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise AmazonAdsError(
                f"Token refresh failed ({resp.status_code}). Check client_id/"
                f"secret/refresh_token. Response: {resp.text[:300]}"
            )
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
        log.info("Refreshed Amazon Ads access token")

    def _ensure_token(self):
        if self._access_token is None or time.time() >= self._expires_at:
            self._refresh()

    def _request(self, method, path, profile_id=None, _auth_retry=True, **kwargs):
        self._ensure_token()
        headers = kwargs.pop("headers", {}) or {}
        headers["Amazon-Advertising-API-ClientId"] = self.client_id
        headers["Authorization"] = f"Bearer {self._access_token}"
        if profile_id is not None:
            headers["Amazon-Advertising-API-Scope"] = str(profile_id)

        resp = self.session.request(
            method, f"{self.base_url}{path}", headers=headers, timeout=self.timeout, **kwargs
        )

        if resp.status_code == 401 and _auth_retry:
            self._refresh()
            return self._request(method, path, profile_id, _auth_retry=False, **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            log.warning("Rate limited; sleeping %ss", wait)
            time.sleep(wait)
            return self._request(method, path, profile_id, _auth_retry=_auth_retry, **kwargs)
        if resp.status_code >= 400:
            raise AmazonAdsError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def get_profiles(self):
        """List advertising profiles tied to this account (one per marketplace)."""
        return self._request("GET", "/v2/profiles")
