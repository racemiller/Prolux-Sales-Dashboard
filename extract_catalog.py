"""
Pull the full SellerCloud product catalog into raw.sellercloud_catalog.

Unlike orders, the catalog is a slowly-changing reference, so this does a full
pull each run and upserts. It lands the entire product record as jsonb (so we
capture MSRP, cost, weight, kit info, etc. even before we've mapped every field)
plus a few extracted columns for convenience.

Reuses your existing sellercloud_client.py.

Usage:
    python extract_catalog.py --init-db
    python extract_catalog.py                 # refresh the catalog
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values, Json
from dotenv import load_dotenv

from sellercloud_client import SellerCloudClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("extract_catalog")

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.sellercloud_catalog (
    product_id    text PRIMARY KEY,
    product_name  text,
    shadow_of     text,
    average_cost  numeric(14,4),
    raw           jsonb NOT NULL,
    extracted_at  timestamptz NOT NULL DEFAULT now()
);
"""

UPSERT = """
INSERT INTO raw.sellercloud_catalog
    (product_id, product_name, shadow_of, average_cost, raw, extracted_at)
VALUES %s
ON CONFLICT (product_id) DO UPDATE SET
    product_name=EXCLUDED.product_name, shadow_of=EXCLUDED.shadow_of,
    average_cost=EXCLUDED.average_cost, raw=EXCLUDED.raw, extracted_at=EXCLUDED.extracted_at;
"""


def iter_catalog(client, page_size=50):
    """Page through /api/catalog until the last page. The endpoint caps pageSize
    at 50 no matter what you ask for, so we can't assume the server honors our
    requested size -- we detect the actual page size from the first response and
    stop on a page shorter than that (or an empty one). Params are
    pageNumber/pageSize here (not model.pageNumber like the orders endpoint)."""
    page = 1
    effective = None
    while True:
        data = client._request("GET", "/api/catalog",
                               params={"pageNumber": page, "pageSize": page_size})
        items = (data or {}).get("Items") if isinstance(data, dict) else data
        items = items or []
        if not items:
            break
        for it in items:
            yield it
        if effective is None:
            effective = len(items)          # the server's real page size
        if len(items) < effective:
            break                            # short page -> last page
        page += 1


def to_num(v):
    if isinstance(v, (dict, list)) or v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def product_to_row(p, now):
    # SellerCloud has used ProductID / ID / Sku across endpoints; take whichever exists.
    pid = p.get("ProductID") or p.get("ID") or p.get("Sku") or p.get("SKU")
    return (
        str(pid) if pid is not None else None,
        p.get("ProductName"),
        (p.get("ShadowOf") or None),
        to_num(p.get("AverageCost")),
        Json(p),
        now,
    )


def connect_db():
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "catalog"), user=os.getenv("POSTGRES_USER", "analytics"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-db", action="store_true")
    ap.add_argument("--page-size", type=int, default=50)
    args = ap.parse_args()

    server_id = os.getenv("SELLERCLOUD_SERVER_ID")
    username = os.getenv("SELLERCLOUD_USERNAME")
    password = os.getenv("SELLERCLOUD_PASSWORD")
    if not all([server_id, username, password]):
        log.error("Missing SELLERCLOUD_SERVER_ID / _USERNAME / _PASSWORD."); sys.exit(1)

    conn = connect_db()
    if args.init_db:
        conn.cursor().execute(SCHEMA); conn.commit(); log.info("Schema applied.")

    client = SellerCloudClient(server_id, username, password)
    now = datetime.now(timezone.utc)
    batch, total, skipped = [], 0, 0
    with conn.cursor() as cur:
        for p in iter_catalog(client, page_size=args.page_size):
            row = product_to_row(p, now)
            if row[0] is None:
                skipped += 1; continue
            batch.append(row)
            if len(batch) >= 500:
                execute_values(cur, UPSERT, batch); conn.commit(); total += len(batch); batch = []
                log.info("Upserted %s products...", total)
        if batch:
            execute_values(cur, UPSERT, batch); conn.commit(); total += len(batch)
    log.info("Done. %s products upserted (%s skipped without an ID).", total, skipped)
    conn.close()


if __name__ == "__main__":
    main()
