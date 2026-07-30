-- Attaches channel + fee logic to each line, then computes profit.
--
-- CHANNEL RESOLUTION: map each order's OrderSource to a channel name. A row in
-- channel_map with a specific company_id (e.g. 6 + 195 = Lowe's) wins over the
-- generic row for that source (6 = Website). Unmapped sources fall to 'Other'.
--
-- UNIFIED CHANNEL FEE (Option A): one fee number per line, by method --
--   from_actuals      -> the fee SellerCloud already captured (FinalValueFee)
--   computed_pct_flat -> revenue * pct + allocated flat fee   (e.g. Shopify)
--   wholesale_none / none -> 0  (wholesale discount is lower revenue, not a fee)
-- This REPLACES the old raw marketplace_fee in the profit math, so Amazon (whose
-- fee was already captured) is unchanged, Shopify now correctly carries its
-- 2.4% + $0.30, and wholesale channels aren't double-counted.

with items as (
    select * from {{ ref('stg_sellercloud_order_items') }}
),

orders as (
    select order_id, created_on, order_shipping_cost, order_source, company_id
    from {{ ref('stg_sellercloud_orders') }}
),

order_revenue as (
    select order_id, sum(revenue) as order_revenue
    from items group by order_id
),

channel_map as (
    select order_source, nullif(trim(company_id), '') as company_id, channel
    from {{ ref('channel_map') }}
),

-- resolve one channel per order; company_id-specific match ranked ahead of generic
orders_resolved as (
    select order_id, created_on, order_shipping_cost, order_source, company_id, channel
    from (
        select
            o.*,
            coalesce(m.channel, 'Other') as channel,
            row_number() over (
                partition by o.order_id
                order by (m.company_id is not null) desc
            ) as rn
        from orders o
        left join channel_map m
          on m.order_source = o.order_source
         and (m.company_id is null or m.company_id = o.company_id)
    ) ranked
    where rn = 1
),

rules as (
    select
        channel,
        fee_method,
        coalesce(fee_pct, 0)::numeric   as fee_pct,
        coalesce(flat_fee, 0)::numeric  as flat_fee,
        channel_pays_shipping
    from {{ ref('channel_fee_rules') }}
),

joined as (
    select
        i.*,
        orv.order_revenue,
        ord.created_on,
        ord.order_source,
        ord.company_id,
        ord.channel,
        ord.order_shipping_cost,
        r.fee_method,
        r.fee_pct,
        r.flat_fee,
        r.channel_pays_shipping
    from items i
    left join orders_resolved ord on i.order_id = ord.order_id
    left join order_revenue   orv on i.order_id = orv.order_id
    left join rules           r   on r.channel  = ord.channel
),

allocated as (
    select
        *,
        case when coalesce(order_revenue, 0) = 0 then 0
             else coalesce(order_shipping_cost, 0) * (revenue / order_revenue) end
             as allocated_shipping_cost,
        case when coalesce(order_revenue, 0) = 0 then 0
             else coalesce(flat_fee, 0) * (revenue / order_revenue) end
             as allocated_flat_fee
    from joined
),

final as (
    select
        *,
        case
            when fee_method = 'from_actuals'      then marketplace_fee
            when fee_method = 'computed_pct_flat' then revenue * fee_pct + allocated_flat_fee
            else 0
        end                                                       as channel_fee,
        -- analytical only, NEVER subtracted in profit: wholesale list-price give-up
        case when fee_method = 'wholesale_none'
             then greatest(unit_price * qty - revenue, 0) else 0 end   as list_discount
    from allocated
)

select
    *,
    created_on                              as ordered_at,
    created_on::date                        as order_date,
    revenue - cogs                          as gross_profit,
    revenue - refunds                       as net_revenue,
    (revenue - refunds) - cogs - channel_fee - allocated_shipping_cost as contribution
from final
