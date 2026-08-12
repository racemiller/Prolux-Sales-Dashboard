"""
Pull return receiving-log submissions from Jotform into raw.jotform_returns.

We land the handful of fields that matter (order/RMA, SKU, channel, reason,
disposition, labor + grand-total cost) as columns, plus the full submission as
jsonb. Disposition mapping, SKU canonicalization, and the returns-vs-warranty
split all happen later in dbt -- this just lands the data.

Usage:
    python extract_jotform_returns.py --init-db
    python extract_jotform_returns.py --since "2026-07-01 00:00:00"
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import execute_values, Json
from dotenv import load_dotenv

from jotform_client import JotformClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("extract_jotform")

# qid -> column. Confirmed against the form's /questions output + sample submissions.
QIDS = {
    "order_rma": "9",
    "sku_raw": "10",
    "channel": "13",
    "reason": "15",
    "disposition": "18",
    "labor_cost": "122",
    "processing_cost": "123",  # GRAND TOTAL COST for this return
}

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.jotform_returns (
    submission_id    text PRIMARY KEY,
    created_at       timestamptz,
    order_rma        text,
    sku_raw          text,
    channel          text,
    reason           text,
    disposition      text,
    labor_cost       numeric(12,2),
    processing_cost  numeric(12,2),
    raw              jsonb NOT NULL,
    extracted_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jotform_created_at ON raw.jotform_returns (created_at);
"""

UPSERT = """
INSERT INTO raw.jotform_returns
    (submission_id, created_at, order_rma, sku_raw, channel, reason,
     disposition, labor_cost, processing_cost, raw, extracted_at)
VALUES %s
ON CONFLICT (submission_id) DO UPDATE SET
    created_at=EXCLUDED.created_at, order_rma=EXCLUDED.order_rma,
    sku_raw=EXCLUDED.sku_raw, channel=EXCLUDED.channel, reason=EXCLUDED.reason,
    disposition=EXCLUDED.disposition, labor_cost=EXCLUDED.labor_cost,
    processing_cost=EXCLUDED.processing_cost, raw=EXCLUDED.raw,
    extracted_at=EXCLUDED.extracted_at;
"""


def answer(sub, qid):
    a = (sub.get("answers") or {}).get(qid) or {}
    return a.get("answer")


def to_text(v):
    """Jotform answers aren't always strings -- time/widget fields come back as
    dicts (e.g. {"hh":"09","mm":"40"}). Coerce anything non-scalar to a string so
    it can land in a text column instead of blowing up psycopg2."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def to_num(v):
    if isinstance(v, (dict, list)) or v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def submission_to_row(sub, now):
    return (
        to_text(sub.get("id")),
        parse_dt(sub.get("created_at")),
        to_text(answer(sub, QIDS["order_rma"])),
        to_text(answer(sub, QIDS["sku_raw"])),
        to_text(answer(sub, QIDS["channel"])),
        to_text(answer(sub, QIDS["reason"])),
        to_text(answer(sub, QIDS["disposition"])),
        to_num(answer(sub, QIDS["labor_cost"])),
        to_num(answer(sub, QIDS["processing_cost"])),
        Json(sub),
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


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-db", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="Pull every submission (full backfill). Use for the first run.")
    ap.add_argument("--lookback-days", type=int, default=30,
                    help="When --since/--all are omitted, pull this many days back (default 30).")
    ap.add_argument("--since", help="Only pull submissions after 'YYYY-MM-DD HH:MM:SS'.")
    args = ap.parse_args()

    api_key = os.getenv("JOTFORM_API_KEY")
    form_id = os.getenv("JOTFORM_RETURNS_FORM_ID")
    if not api_key or not form_id:
        log.error("Set JOTFORM_API_KEY and JOTFORM_RETURNS_FORM_ID (see .env).")
        sys.exit(1)

    conn = connect_db()
    if args.init_db:
        conn.cursor().execute(SCHEMA)
        conn.commit()
        log.info("Schema applied.")

    client = JotformClient(api_key, base_url=os.getenv("JOTFORM_BASE_URL", "https://api.jotform.com"))
    now = datetime.now(timezone.utc)

    # Decide the window: explicit --since wins; --all pulls everything; otherwise
    # a rolling lookback so a bare `python extract_jotform_returns.py` in cron
    # re-pulls recent submissions and upserts them (idempotent).
    if args.since:
        since = args.since
    elif args.all:
        since = None
    else:
        since = (now - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
    log.info("Pulling submissions since: %s", since or "(all)")

    batch, total = [], 0
    with conn.cursor() as cur:
        for sub in client.iter_submissions(form_id, since=since):
            batch.append(submission_to_row(sub, now))
            if len(batch) >= 500:
                execute_values(cur, UPSERT, batch)
                conn.commit(); total += len(batch); batch = []
                log.info("Upserted %s...", total)
        if batch:
            execute_values(cur, UPSERT, batch); conn.commit(); total += len(batch)
    log.info("Done. %s submissions upserted.", total)
    conn.close()


if __name__ == "__main__":
    main()
