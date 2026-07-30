"""
One-time Amazon Ads onboarding. Run this AFTER your Direct Advertiser API
access is approved and you've assigned API access to your LwA security profile.

It will:
  1. Print the authorization URL (scope spelled correctly).
  2. Take the redirected URL/code you paste back.
  3. Exchange it for a long-lived refresh token.
  4. List your advertising profiles so you can grab the profile ID.

Then you copy the refresh token + profile ID into your .env and you're done.

Set these first (env vars or you'll be prompted):
  AMAZON_ADS_CLIENT_ID, AMAZON_ADS_CLIENT_SECRET
  AMAZON_ADS_REDIRECT_URI  (must EXACTLY match an Allowed Return URL on your
                            security profile; default https://localhost:443)
  AMAZON_ADS_REGION        (NA for US/CA/MX; default NA)
"""

import os
import sys
import urllib.parse

import requests

from amazon_ads_client import AmazonAdsClient, TOKEN_ENDPOINTS

# LwA authorization pages differ by region.
AUTH_PAGES = {
    "NA": "https://www.amazon.com/ap/oa",
    "EU": "https://eu.account.amazon.com/ap/oa",
    "FE": "https://apac.account.amazon.com/ap/oa",
}

# The double colon here is the #1 thing people get wrong.
SCOPE = "advertising::campaign_management"


def build_auth_url(client_id, redirect_uri, region):
    params = {
        "client_id": client_id,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    return AUTH_PAGES[region] + "?" + urllib.parse.urlencode(params)


def extract_code(pasted):
    """Accept either the full redirected URL or just the raw code value."""
    pasted = pasted.strip()
    if "code=" in pasted:
        query = urllib.parse.urlparse(pasted).query
        code = urllib.parse.parse_qs(query).get("code", [None])[0]
        if code:
            return code
    return pasted  # assume they pasted just the code


def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri, region):
    resp = requests.post(
        TOKEN_ENDPOINTS[region],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"\nToken exchange failed ({resp.status_code}): {resp.text[:400]}", file=sys.stderr)
        print("Common causes: redirect_uri doesn't match the Allowed Return URL "
              "exactly, the code was already used (get a fresh one), or API access "
              "isn't assigned to this LwA app yet.", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def main():
    client_id = os.getenv("AMAZON_ADS_CLIENT_ID") or input("LwA Client ID: ").strip()
    client_secret = os.getenv("AMAZON_ADS_CLIENT_SECRET") or input("LwA Client Secret: ").strip()
    redirect_uri = os.getenv("AMAZON_ADS_REDIRECT_URI", "https://localhost:443")
    region = os.getenv("AMAZON_ADS_REGION", "NA")

    print("\n" + "=" * 70)
    print("STEP 1 — Authorize")
    print("=" * 70)
    print("Open this URL in a browser signed into the Amazon account that OWNS")
    print("your ads (use an incognito window if you're logged into several),")
    print("approve access, then copy the URL you land on from the address bar.")
    print("(The page itself will look broken since it's localhost — that's fine;")
    print(" you only need the ?code=... in the address bar.)\n")
    print(build_auth_url(client_id, redirect_uri, region))
    print()

    pasted = input("Paste the redirected URL (or just the code): ")
    code = extract_code(pasted)

    print("\nExchanging authorization code for a refresh token...")
    tokens = exchange_code_for_tokens(client_id, client_secret, code, redirect_uri, region)
    refresh_token = tokens["refresh_token"]

    print("\nFetching your advertising profiles...")
    client = AmazonAdsClient(client_id, client_secret, refresh_token, region)
    profiles = client.get_profiles()

    print("\n" + "=" * 70)
    print("DONE — copy these into your .env")
    print("=" * 70)
    print(f"\nAMAZON_ADS_REFRESH_TOKEN={refresh_token}\n")
    print("Your advertising profiles (pick the US Sponsored Products one):\n")
    for p in profiles:
        info = p.get("accountInfo", {}) or {}
        print(f"  profileId={p.get('profileId')}  "
              f"country={p.get('countryCode')}  "
              f"type={info.get('type')}  "
              f"name={info.get('name')}")
    print("\nThen set:  AMAZON_ADS_PROFILE_ID=<the profileId you chose>")


if __name__ == "__main__":
    main()
