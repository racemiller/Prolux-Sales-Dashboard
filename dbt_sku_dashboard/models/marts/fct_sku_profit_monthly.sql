with items as (select * from {{ ref('int_order_items_costed') }})
select
    sku || '|' || to_char(date_trunc('month', ordered_at), 'YYYY-MM') as sku_month,
    date_trunc('month', ordered_at)::date    as month,
    sku,
    max(product_name)                        as product_name,
    count(*)                                  as sales,
    count(distinct order_id)                  as orders,
    sum(qty)                                  as units_sold,
    round(sum(revenue), 2)                    as gross_revenue,
    round(sum(net_revenue), 2)                as net_revenue,
    round(sum(cogs), 2)                       as cogs,
    round(sum(channel_fee), 2)                as channel_fees,
    round(sum(allocated_shipping_cost), 2)    as shipping_cost,
    round(sum(gross_profit), 2)               as gross_profit,
    round(sum(contribution), 2)               as contribution,
    case when sum(net_revenue) = 0 then null
         else round(sum(contribution) / sum(net_revenue), 4) end as contribution_margin_pct
from items
group by 1, 2, 3
