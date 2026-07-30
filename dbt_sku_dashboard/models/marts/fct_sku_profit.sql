with items as (select * from {{ ref('int_order_items_costed') }})
select
    sku,
    max(product_name)                        as product_name,
    bool_or(is_bundle)                        as has_bundle_lines,
    count(*)                                  as sales,
    count(distinct order_id)                  as orders,
    sum(qty)                                  as units_sold,
    sum(qty_returned)                         as units_returned,
    round(sum(revenue), 2)                    as gross_revenue,
    round(sum(refunds), 2)                    as refunds,
    round(sum(net_revenue), 2)                as net_revenue,
    round(sum(cogs), 2)                       as cogs,
    round(sum(channel_fee), 2)                as channel_fees,
    round(sum(channel_fee) / nullif(count(*),0), 2)          as avg_channel_fee_per_sale,
    round(avg(allocated_shipping_cost) filter (where allocated_shipping_cost > 0), 2) as avg_shipping_cost,
    round(sum(allocated_shipping_cost), 2)    as shipping_cost,
    round(sum(gross_profit), 2)               as gross_profit,
    round(sum(contribution), 2)               as contribution,
    case when sum(net_revenue) = 0 then null
         else round(sum(contribution) / sum(net_revenue), 4) end as contribution_margin_pct
from items
group by sku
