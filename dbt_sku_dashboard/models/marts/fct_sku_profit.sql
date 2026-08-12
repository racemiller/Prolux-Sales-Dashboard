-- Headline table: one row per canonical SKU (shadows rolled into parents).
--
-- MARGIN DENOMINATORS -- three, deliberately, because they answer different
-- questions and conflating them is how the 32%-vs-36% confusion happened:
--   * contribution_margin_pct        contribution / net revenue  (margin on what you kept)
--   * contribution_margin_pct_gross  contribution / gross revenue (before refunds)
--   * contribution_margin_pct_msrp   contribution / (MSRP x units) -- matches the
--     spreadsheet's Net Profit % convention. MSRP comes from the catalog's
--     SitePrice, one authoritative value per product.
--
-- Cost here is cost-at-time-of-sale. See fct_sku_cost_watch for current cost.

with items as (
    select * from {{ ref('int_order_items_costed') }}
),

catalog as (
    select canonical_sku, max(msrp) as msrp, bool_or(is_active) as is_active
    from {{ ref('stg_sellercloud_catalog') }}
    group by canonical_sku
),

agg as (
    select
        sku,
        max(product_name)                        as product_name,
        bool_or(is_bundle)                       as has_bundle_lines,
        count(*)                                 as sales,
        count(distinct order_id)                 as orders,
        sum(qty)                                 as units_sold,
        sum(qty_returned)                        as units_returned,
        round(sum(revenue), 2)                   as gross_revenue,
        round(sum(refunds), 2)                   as refunds,
        round(sum(net_revenue), 2)               as net_revenue,
        round(sum(cogs), 2)                      as cogs,
        round(sum(channel_fee), 2)               as channel_fees,
        round(sum(channel_fee) / nullif(count(*), 0), 2) as avg_channel_fee_per_sale,
        round(avg(allocated_shipping_cost) filter (where allocated_shipping_cost > 0), 2) as avg_shipping_cost,
        round(sum(allocated_shipping_cost), 2)   as shipping_cost,
        round(sum(gross_profit), 2)              as gross_profit,
        round(sum(contribution), 2)              as contribution
    from items
    group by sku
)

select
    a.*,
    c.msrp,
    c.is_active,
    round(a.contribution / nullif(a.units_sold, 0), 2)     as contribution_per_unit,

    case when a.net_revenue = 0 then null
         else round(a.contribution / a.net_revenue, 4) end as contribution_margin_pct,
    case when a.gross_revenue = 0 then null
         else round(a.contribution / a.gross_revenue, 4) end as contribution_margin_pct_gross,
    case when coalesce(c.msrp, 0) = 0 or a.units_sold = 0 then null
         else round(a.contribution / (c.msrp * a.units_sold), 4) end as contribution_margin_pct_msrp
from agg a
left join catalog c on c.canonical_sku = a.sku
