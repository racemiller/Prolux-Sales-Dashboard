-- FORWARD-LOOKING pricing signal (deliberately separate from historical P&L).
--
-- Answers: "what has this product's cost done lately, and what would my margin
-- be if I sold it at today's cost?" Historical profit models keep using the
-- cost captured at time of sale; nothing here restates history.
--
-- current_unit_cost prefers the catalog's LastCost (the most recent price
-- actually paid) and falls back to AverageCost when LastCost is missing/zero.
-- cost_change_pct compares that to the weighted average cost you ACTUALLY sold
-- at over the window, so a positive number means costs have risen since.

{% set window_days = 90 %}

with items as (
    select * from {{ ref('int_order_items_costed') }}
),

recent as (
    select
        sku,
        sum(qty)                                    as units_sold_window,
        sum(cogs)                                   as cogs_window,
        sum(revenue)                                as revenue_window,
        sum(contribution)                           as contribution_window,
        -- what you actually paid, weighted by units, over the window
        sum(cogs) / nullif(sum(qty), 0)             as at_sale_unit_cost,
        sum(revenue) / nullif(sum(qty), 0)          as avg_selling_price,
        -- per-unit costs other than COGS (fees + shipping), held constant
        (sum(channel_fee) + sum(allocated_shipping_cost)) / nullif(sum(qty), 0) as other_unit_costs
    from items
    where ordered_at >= current_date - interval '{{ window_days }} days'
    group by sku
),

catalog as (
    select
        canonical_sku,
        max(msrp)                                           as msrp,
        max(current_cost)                                   as current_cost,
        bool_or(is_active)                                  as is_active
    from {{ ref('stg_sellercloud_catalog') }}
    group by canonical_sku
),

joined as (
    select
        r.sku,
        c.is_active,
        c.msrp,
        r.units_sold_window,
        round(r.avg_selling_price, 2)                       as avg_selling_price,
        round(r.at_sale_unit_cost, 2)                       as at_sale_unit_cost,
        round(c.current_cost, 2)                            as current_unit_cost,
        round(r.other_unit_costs, 2)                        as other_unit_costs,
        round(r.contribution_window, 2)                     as contribution_window,
        round(r.contribution_window / nullif(r.units_sold_window, 0), 2) as contribution_per_unit_actual
    from recent r
    left join catalog c on c.canonical_sku = r.sku
)

select
    *,
    -- how much the cost has moved since what you actually sold at
    round(current_unit_cost - at_sale_unit_cost, 2)         as unit_cost_change,
    case when coalesce(at_sale_unit_cost, 0) = 0 then null
         else round((current_unit_cost - at_sale_unit_cost) / at_sale_unit_cost, 4)
    end                                                     as cost_change_pct,

    -- what per-unit contribution WOULD be at today's cost, same price and fees
    round(avg_selling_price - current_unit_cost - other_unit_costs, 2)
                                                            as contribution_per_unit_at_current_cost,
    case when coalesce(avg_selling_price, 0) = 0 then null
         else round((avg_selling_price - current_unit_cost - other_unit_costs) / avg_selling_price, 4)
    end                                                     as margin_pct_at_current_cost,

    -- flags for a "needs a price review" dashboard
    (avg_selling_price - current_unit_cost - other_unit_costs) < 0            as sells_at_a_loss_now,
    (current_unit_cost > at_sale_unit_cost * 1.10)                            as cost_up_over_10pct
from joined
