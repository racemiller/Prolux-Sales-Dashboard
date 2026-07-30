# SKU Dashboard — dbt models

Turns `raw.sellercloud_orders` into clean, tested profit tables. All the logic we
worked out by hand (flattening line items, canonical SKU rollup, discount-adjusted
revenue, at-sale COGS, marketplace fees, shipping allocation) lives here as
version-controlled models instead of pasted SQL.

## Model layout

```
staging/     stg_sellercloud_orders        one row per order (headers + costs)
             stg_sellercloud_order_items   one row per line; defines canonical SKU
intermediate int_order_items_costed        allocates order shipping, computes profit
marts/       fct_order_item_profit         line-grain fact (drill-down / audit)
             fct_sku_profit                >>> the headline: profit per SKU <<<
```

Lineage: `raw.sellercloud_orders` → staging → intermediate → marts.

## Setup

1. Install: `pip install dbt-postgres`
2. Copy `profiles.yml` to `~/.dbt/profiles.yml` (or keep it here and set
   `DBT_PROFILES_DIR` to this folder). It reads the same `POSTGRES_*` env vars
   as the extraction script.
3. Build + test:
   ```bash
   dbt run      # builds all 5 models
   dbt test     # runs uniqueness / not-null checks
   ```
4. Query `analytics.fct_sku_profit` (in Adminer, or point Metabase at it).

## The measure ladder (fct_sku_profit)

| Measure | Meaning |
|---|---|
| `gross_revenue` | Sum of LineTotal (already discount-adjusted) |
| `net_revenue` | gross_revenue − refunds |
| `gross_profit` | gross_revenue − COGS |
| `contribution` | net_revenue − COGS − marketplace_fees − shipping_cost |
| `contribution_margin_pct` | contribution ÷ net_revenue |

`contribution` is your best profit number **from SellerCloud data alone**. Ad
spend and overhead are not in it yet — they attach at this same SKU grain once
those sources are loaded.

## Configurable bits (dbt_project.yml `vars`)

- `excluded_order_status_codes`: list of SellerCloud StatusCodes to drop from
  profit (e.g. cancelled orders). Empty by default — set once you confirm the
  codes in SellerCloud.

## Known limitations (deliberately deferred)

- **Bundles/kits**: lines where `is_bundle = true` carry the kit's revenue, but
  the kit's cost may not decompose cleanly to components. Flagged, not yet split.
- **Returns**: `refunds` (TotalRefunded) is netted into `net_revenue`, but
  returned COGS isn't added back to inventory here (that's an inventory concern).
- **Shipping** is allocated by revenue share. Swap the basis in
  `int_order_items_costed` if you prefer weight or unit count.

## Next

- Load ad spend (Google/Facebook/Amazon via Airbyte) into `raw.*`, add a
  `stg_ad_spend`, and attach spend to SKUs in a new mart alongside contribution.
- Add allocated overhead (warehousing, payroll) the same way shipping works now.
- Point Metabase at `analytics.fct_sku_profit` for dashboards and history.
