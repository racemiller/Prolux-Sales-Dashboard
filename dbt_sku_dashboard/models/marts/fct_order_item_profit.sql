-- Line grain, date-stamped, channel-tagged, fully costed.
select
    order_item_id,
    order_id,
    order_date,
    ordered_at,
    channel,
    sku,
    source_sku,
    parent_sku,
    product_name,
    is_bundle,
    qty,
    qty_returned,
    revenue,
    net_revenue,
    cogs,
    channel_fee,
    marketplace_fee                    as marketplace_fee_captured,  -- raw FinalValueFee, for reference
    round(allocated_shipping_cost, 2)  as allocated_shipping_cost,
    round(list_discount, 2)            as list_discount,             -- analytical only
    refunds,
    gross_profit,
    round(contribution, 2)             as contribution
from {{ ref('int_order_items_costed') }}
