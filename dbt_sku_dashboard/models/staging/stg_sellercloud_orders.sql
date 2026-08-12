with s as (select * from {{ source('raw','sellercloud_orders') }})
select order_id, order_source, (raw->>'CompanyID') as company_id, status_code, created_on, last_updated, grand_total,
  coalesce((raw->>'ShippingTotal')::numeric,0) as shipping_charged_to_customer,
  coalesce((raw->>'FinalShippingFee')::numeric,0) as order_shipping_cost,
  order_source_order_id, raw->>'CompanyName' as company_name, raw->>'OrderSourceUrl' as order_source_url
from s
{% if var('excluded_order_status_codes') | length > 0 %}
where status_code not in ({{ var('excluded_order_status_codes') | join(', ') }})
{% endif %}
