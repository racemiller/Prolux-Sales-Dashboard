-- SKU x channel grain: sales per channel per SKU, avg fee, avg shipping.
-- The overall weighted-average channel fee per SKU falls out of this table by
-- grouping to SKU: sum(channel_fee_total) / sum(sales).
with items as (select * from {{ ref('int_order_items_costed') }})
select
    sku || '|' || channel                    as sku_channel,
    sku,
    channel,
    max(fee_method)                          as fee_method,
    count(*)                                  as sales,
    count(distinct order_id)                  as orders,
    sum(qty)                                  as units_sold,
    round(sum(revenue), 2)                    as gross_revenue,
    round(sum(channel_fee), 2)                as channel_fee_total,
    round(sum(channel_fee) / nullif(count(*),0), 2) as avg_fee_per_sale,
    case when sum(revenue) = 0 then null
         else round(sum(channel_fee) / sum(revenue), 4) end as avg_fee_pct,
    round(avg(allocated_shipping_cost) filter (where allocated_shipping_cost > 0), 2) as avg_shipping_cost,
    round(sum(list_discount), 2)             as list_discount_total  -- analytical (wholesale), not in profit
from items
group by sku, channel
