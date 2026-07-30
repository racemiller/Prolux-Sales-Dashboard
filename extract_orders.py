"""
Pull SellerCloud orders into Postgres (raw.sellercloud_orders).

Design notes
------------
* ELT, not ETL: we land orders almost raw (full JSON + a few extracted columns)
  and defer all profit math to dbt. This keeps ingestion simple and durable.
* Upsert on order_id, so re-running is safe and idempotent.
* Rolling re-pull: each run re-pulls a window of recent orders by created date
  and upserts them, which catches late edits (refunds, status/shipping changes)
  without needing a separate "updated since" query. Widen --backfill-days for
  the first full load.

Usage
-----
    python extract_orders.py --init-db            # create schema, then sync
    python extract_orders.py                      # sync last 30 days (default)
    python extract_orders.py --backfill-days 730  # backfill ~2 years
    python extract_orders.py --since 01/01/2024 --until 03/31/2024

Configure credentials in a .env file (see .env.example).
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values, Json
from dotenv import load_dotenv

from sellercloud_client import SellerCloudClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("extract_orders")

# SellerCloud's docs are inconsistent on date format (the working Get All Orders
# example uses yyyy/mm/dd). If a date-filtered call errors, try "%m/%d/%Y".
DATE_FORMAT = "%Y/%m/%d"

UPSERT_SQL = """
INSERT INTO raw.sellercloud_orders
    (order_id, order_source_order_id, created_on, last_updated,
     grand_total, order_source, status_code, raw, extracted_at)
VALUES %s
ON CONFLICT (order_id) DO UPDATE SET
    order_source_order_id = EXCLUDED.order_source_order_id,
    created_on            = EXCLUDED.created_on,
    last_updated          = EXCLUDED.last_updated,
    grand_total           = EXCLUDED.grand_total,
    order_source          = EXCLUDED.order_source,
    status_code           = EXCLUDED.status_code,
    raw                   = EXCLUDED.raw,
    extracted_at          = EXCLUDED.extracted_at;
"""


def upsert_orders(cur, rows):
    """
    Upsert a batch, de-duplicating by order_id first.

    A single INSERT ... ON CONFLICT statement can't touch the same key twice,
    so if SellerCloud's paging hands us the same order_id more than once within
    one batch (it can, because page-number paging over a large set isn't a
    perfectly stable sort), Postgres raises CardinalityViolation. Collapsing to
    the last occurrence avoids that. Duplicates that span *different* batches are
    harmless -- they just become normal updates in separate statements.

    order_id is element 0 of each row tuple (see order_to_row).
    """
    deduped = {row[0]: row for row in rows}   # last occurrence wins
    execute_values(cur, UPSERT_SQL, list(deduped.values()))
    return len(deduped)


def parse_dt(value):
    """SellerCloud returns ISO-ish strings like 2024-08-19T10:44:20.543Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def order_to_row(order, now):
    return (
        order.get("ID"),
        order.get("OrderSourceOrderID"),
        parse_dt(order.get("CreatedOn")),
        parse_dt(order.get("LastUpdated")),
        order.get("GrandTotal"),
        order.get("OrderSource"),
        order.get("StatusCode"),
        Json(order),   # full raw payload -> jsonb
        now,
    )


def connect_db():
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "catalog"),
        user=os.getenv("POSTGRES_USER", "analytics"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def apply_schema(conn):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "schema.sql"), "r", encoding="utf-8") as f:
        conn.cursor().execute(f.read())
    conn.commit()
    log.info("Schema applied (idempotent).")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-db", action="store_true",
                    help="Create the schema before syncing.")
    ap.add_argument("--backfill-days", type=int, default=30,
                    help="How many days back to pull when --since is omitted.")
    ap.add_argument("--since", help=f"Start date, format {DATE_FORMAT}.")
    ap.add_argument("--until", help=f"End date, format {DATE_FORMAT}.")
    ap.add_argument("--page-size", type=int, default=50)
    args = ap.parse_args()

    server_id = os.getenv("SELLERCLOUD_SERVER_ID")
    username = os.getenv("SELLERCLOUD_USERNAME")
    password = os.getenv("SELLERCLOUD_PASSWORD")
    if not all([server_id, username, password]):
        log.error("Missing SELLERCLOUD_SERVER_ID / _USERNAME / _PASSWORD. "
                  "Copy .env.example to .env and fill it in.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    until = args.until or now.strftime(DATE_FORMAT)
    since = args.since or (now - timedelta(days=args.backfill_days)).strftime(DATE_FORMAT)

    conn = connect_db()
    if args.init_db:
        apply_schema(conn)

    client = SellerCloudClient(server_id, username, password)

    log.info("Pulling orders created %s -> %s", since, until)
    batch, total = [], 0
    with conn.cursor() as cur:
        for order in client.iter_orders(since, until, page_size=args.page_size):
            batch.append(order_to_row(order, now))
            if len(batch) >= 500:
                total += upsert_orders(cur, batch)
                conn.commit()
                log.info("Upserted %s orders so far...", total)
                batch = []
        if batch:
            total += upsert_orders(cur, batch)
            conn.commit()

        cur.execute(
            """
            INSERT INTO raw.sync_state (source, last_run_at, watermark)
            VALUES ('sellercloud_orders', %s, %s)
            ON CONFLICT (source) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                watermark   = EXCLUDED.watermark;
            """,
            (now, now),
        )
        conn.commit()

    log.info("Done. %s orders upserted.", total)
    conn.close()


if __name__ == "__main__":
    main()
