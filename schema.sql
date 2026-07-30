-- Raw landing layer. We keep the full order JSON in `raw` (jsonb) and pull a
-- few top-level columns out for indexing and incremental logic. All the real
-- cost/revenue/profit calculations happen LATER (in dbt), reading from these
-- tables. Landing data close to raw means schema changes on SellerCloud's side
-- don't break ingestion -- you just adjust the transform layer.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.sellercloud_orders (
    order_id               bigint PRIMARY KEY,
    order_source_order_id  text,
    created_on             timestamptz,
    last_updated           timestamptz,
    grand_total            numeric(14,2),
    order_source           integer,
    status_code            integer,
    raw                    jsonb NOT NULL,
    extracted_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sc_orders_created_on
    ON raw.sellercloud_orders (created_on);
CREATE INDEX IF NOT EXISTS idx_sc_orders_last_updated
    ON raw.sellercloud_orders (last_updated);

-- Tracks the last successful sync per source so runs can be incremental.
CREATE TABLE IF NOT EXISTS raw.sync_state (
    source       text PRIMARY KEY,
    last_run_at  timestamptz,
    watermark    timestamptz   -- e.g. max created_on successfully pulled
);
