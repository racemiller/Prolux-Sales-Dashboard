-- Cleans the raw Jotform receiving log into one row per (submission, SKU):
--   * splits comma-separated SKUs, allocating processing cost evenly
--   * maps disposition text -> category + P&L routing flags
--   * matches the hand-typed SKU to a canonical SKU in priority order:
--       1. explicit alias (sku_aliases seed)            -> 'alias'
--       2. exact match (lowercased/trimmed)             -> 'exact'
--       3. normalized match (alphanumeric-only, e.g.    -> 'normalized'
--          'SS7000Stainless' == 'ss7000_stainless')
--       4. no match                                     -> 'unmatched'
--
-- The normalized tier only fires when a normalized key maps to exactly ONE
-- real SKU -- if two different SKUs normalize the same, it's left unmatched
-- rather than guessed, so we never silently merge distinct products.

with raw_returns as (
    select * from {{ source('raw', 'jotform_returns') }}
),

exploded as (
    select
        r.submission_id, r.created_at, r.order_rma, r.channel, r.reason,
        r.disposition, r.labor_cost, r.processing_cost,
        trim(part) as sku_entered
    from raw_returns r
    cross join lateral unnest(string_to_array(coalesce(r.sku_raw, ''), ',')) as part
    where trim(part) <> ''
),

prepared as (
    select
        e.*,
        lower(trim(sku_entered))                                    as key_exact,
        regexp_replace(lower(trim(sku_entered)), '[^a-z0-9]+', '', 'g') as key_fuzzy,
        count(*) over (partition by submission_id)                  as skus_in_submission,
        round(coalesce(processing_cost, 0)
              / nullif(count(*) over (partition by submission_id), 0), 2) as processing_cost_alloc,
        case
            when upper(disposition) like 'NEW OPEN BOX%' then 'open_box'
            when upper(disposition) like 'NEW%'          then 'new'
            when upper(disposition) like 'REFURBISHED%'  then 'refurbished'
            when upper(disposition) like 'USED%'         then 'used'
            when upper(disposition) like 'WARRANTY%'     then 'warranty'
            when upper(disposition) like 'PARTS%'        then 'scrapped'
            else 'unknown'
        end                                                         as disposition_category
    from exploded e
),

-- every product in the CATALOG (all of them -- sold or not, active or not),
-- in both its own form and its canonical (parent) form. Using the catalog
-- instead of only sold items is what lets returns for products that haven't
-- sold recently still match.
sku_universe as (
    select sku as raw_sku, canonical_sku
    from {{ ref('stg_sellercloud_catalog') }} where coalesce(trim(sku), '') <> ''
    union
    select canonical_sku as raw_sku, canonical_sku
    from {{ ref('stg_sellercloud_catalog') }} where coalesce(trim(canonical_sku), '') <> ''
),

ref_exact as (
    select lower(trim(raw_sku)) as k, min(canonical_sku) as canonical_sku
    from sku_universe
    group by lower(trim(raw_sku))
),

-- normalized reference, guarded: only keys that map to a single canonical SKU
ref_fuzzy as (
    select regexp_replace(lower(trim(raw_sku)), '[^a-z0-9]+', '', 'g') as k,
           min(canonical_sku) as canonical_sku
    from sku_universe
    group by regexp_replace(lower(trim(raw_sku)), '[^a-z0-9]+', '', 'g')
    having count(distinct canonical_sku) = 1
),

aliases as (
    select lower(trim(jotform_sku)) as k, min(canonical_sku) as canonical_sku
    from {{ ref('sku_aliases') }}
    where coalesce(trim(jotform_sku), '') <> ''
    group by lower(trim(jotform_sku))
)

select
    p.submission_id || '|' || p.key_exact       as return_line_id,
    p.submission_id,
    p.created_at,
    p.order_rma,
    p.channel                                    as channel_reported,
    p.reason,
    p.disposition,
    p.disposition_category,

    p.sku_entered,
    p.key_exact                                  as sku_norm,
    coalesce(al.canonical_sku, re.canonical_sku, rf.canonical_sku, p.sku_entered) as sku,
    case
        when al.canonical_sku is not null then 'alias'
        when re.canonical_sku is not null then 'exact'
        when rf.canonical_sku is not null then 'normalized'
        else 'unmatched'
    end                                          as sku_match_status,

    p.skus_in_submission,
    p.processing_cost                            as submission_processing_cost,
    p.processing_cost_alloc                      as processing_cost,
    p.labor_cost,

    (p.disposition_category = 'warranty')                as is_warranty,
    (p.disposition_category in ('new', 'open_box'))      as resells_as_new,
    (p.disposition_category in ('used', 'refurbished'))  as resells_as_sd,
    (p.disposition_category = 'scrapped')                as is_scrapped
from prepared p
left join aliases   al on al.k = p.key_exact
left join ref_exact re on re.k = p.key_exact
left join ref_fuzzy rf on rf.k = p.key_fuzzy
