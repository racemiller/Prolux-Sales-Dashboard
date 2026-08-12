with c as (select * from {{ source('raw','sellercloud_catalog') }})
select
    product_id                                              as sku,
    coalesce(nullif(raw->>'ShadowOf',''), product_id)       as canonical_sku,
    nullif(raw->>'ShadowOf','')                             as parent_sku,
    coalesce(product_name, raw->>'ProductName')             as product_name,
    raw->>'ActiveStatus'                                    as active_status,
    (raw->>'ActiveStatus' = 'Active')                       as is_active,
    (raw->>'IsEndOfLife')::boolean                          as is_end_of_life,
    (raw->>'IsKit')::boolean                                as is_kit,
    (raw->>'SitePrice')::numeric                            as msrp,           -- = SitePrice (confirmed)
    coalesce(average_cost,(raw->>'AverageCost')::numeric)   as average_cost,
    (raw->>'LastCost')::numeric                             as last_cost,
    -- current/replacement cost: most recent price paid, falling back to average
    coalesce(nullif((raw->>'LastCost')::numeric, 0),
             (raw->>'AverageCost')::numeric)                as current_cost,
    raw->>'BrandName'                                       as brand,
    raw->>'ProductType'                                     as product_type,
    (raw->>'WeightLbs')::numeric                            as weight_lbs
from c
