with orders as (select order_id, raw from {{ source('raw','sellercloud_orders') }}),
items as (
    select o.order_id, item from orders o
    cross join lateral jsonb_array_elements(case when jsonb_typeof(o.raw->'Items')='array' then o.raw->'Items' else '[]'::jsonb end) as item
)
select
    order_id,
    (item->>'ID')::bigint                                        as order_item_id,
    item->>'ProductID'                                           as source_sku,
    nullif(item->>'ShadowOf','')                                 as parent_sku,
    coalesce(nullif(item->>'ShadowOf',''), item->>'ProductID')    as sku,
    item->>'ProductName'                                         as product_name,
    coalesce((item->>'Qty')::numeric,0)                          as qty,
    coalesce((item->>'QtyReturned')::numeric,0)                  as qty_returned,
    (item->>'SitePrice')::numeric                                as unit_price,
    coalesce((item->>'LineTotal')::numeric,0)                    as revenue,
    (item->>'AverageCost')::numeric                              as unit_cost,
    coalesce((item->>'Qty')::numeric,0)*coalesce((item->>'AverageCost')::numeric,0) as cogs,
    coalesce((item->>'FinalValueFee')::numeric,0)                as marketplace_fee,
    coalesce((item->>'TotalRefunded')::numeric,0)                as refunds,
    jsonb_array_length(coalesce(item->'BundleItems','[]'::jsonb)) > 0 as is_bundle
from items
