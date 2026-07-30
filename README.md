# SKU Dashboard — Stage 1: SellerCloud → Postgres

The first slice of the pipeline: pull SellerCloud orders into a self-hosted
Postgres database. Later stages add ad spend, dbt transforms, and a Metabase
dashboard.

## What's here

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Self-hosted Postgres + Adminer (a web DB browser) |
| `schema.sql` | The `raw` landing tables |
| `sellercloud_client.py` | API client; handles token auth + refresh |
| `extract_orders.py` | Pulls orders, upserts into Postgres |
| `.env.example` | Template for credentials/config |
| `requirements.txt` | Python dependencies |

## One-time setup

1. **Confirm API access first (no code).** Go to
   `https://{server_id}.api.sellercloud.com/rest/swagger`, use the `api/token`
   call with your integration user's username/password, paste `Bearer {token}`
   into the authorize box, and try **Get All Orders**. If orders come back,
   you're good. A 401 here means the user needs REST API permissions in Delta.

2. **Start Postgres:**
   ```bash
   cp .env.example .env      # then edit .env with real values
   docker compose up -d      # Postgres on :5432, Adminer on :8080
   ```

3. **Install Python deps** (a virtualenv is fine):
   ```bash
   pip install -r requirements.txt
   ```

## Run it

```bash
# First run: create the schema, then backfill ~2 years of orders
python extract_orders.py --init-db --backfill-days 730

# Routine run (e.g. daily via cron): re-pull + upsert the last 30 days,
# which also catches refunds/edits to recent orders
python extract_orders.py
```

Browse the data at http://localhost:8080 (Adminer), or:
```sql
SELECT count(*), sum(grand_total) FROM raw.sellercloud_orders;
```

## Schedule it (later)

A cron entry is enough to start:
```
# every day at 2am
0 2 * * * cd /path/to/sku-dashboard && /path/to/python extract_orders.py >> sync.log 2>&1
```

## Notes / things to confirm on your account

- **Date format:** SellerCloud's docs are inconsistent. The client defaults to
  `yyyy/mm/dd` (what their working example uses). If a date-filtered call errors,
  switch `DATE_FORMAT` in `extract_orders.py` to `%m/%d/%Y`.
- **Token lifetime:** handled automatically — the client reads `expires_in` and
  refreshes early, and re-authenticates on a 401.
- **Design:** orders are landed almost raw (full JSON in a `jsonb` column plus a
  few extracted columns). All profit math happens later in dbt, so ingestion
  stays simple and won't break if SellerCloud tweaks their schema.

## Next stages

1. Add extractors for **purchase orders** and **inventory/catalog** (same
   pattern — new `iter_*` method + `raw.sellercloud_*` table).
2. Add **ad spend** (Google / Facebook / Amazon) via Airbyte.
3. Add **dbt** for the cost/revenue/profit models and expense allocation.
4. Point **Metabase** at Postgres for dashboards.
