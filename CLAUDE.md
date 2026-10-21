# frappe-webshop (soft fork) — Agent Operating Guide

Rebasable soft fork of [frappe/webshop](https://github.com/frappe/webshop). `upstream` =
frappe/webshop, `origin` = JamesonRGrieve/frappe-webshop. The fork's working branch is
**`version-16`** (tracks `upstream/version-16`, matching the production bench's Frappe/ERPNext
v16). Rebase it onto new upstream `version-16` releases; never reformat upstream files.

## Why the fork exists

Upstream Webshop has exactly one store per Frappe site: `Webshop Settings` is a singleton
(one company, price list, customer group, quotation series, checkout/payment setup). One
ERPNext instance here hosts several separate businesses (they share the instance for asset
transfers), each needing its own public store on its own domain. The fork adds **multiple
stores per site**.

## Architecture (fork additions)

- **`Webshop Store`** (new doctype, `webshop/webshop/doctype/webshop_store/`): the per-business
  fields of Webshop Settings (`STORE_FIELDS` in `store.py`: company, price_list,
  default_customer_group, quotation_series, save_quotations_as_draft, enable_checkout,
  payment_success_url, payment_gateway_account, show_price, hide_price_for_guest,
  show_stock_availability, allow_items_not_in_stock, show_quantity_in_website,
  show_contact_us_button). One store per company (orders/payment requests find their store by
  company). Validation reuses `WebshopSettings.validate_price_list_exchange_rate` on an overlaid
  copy. Global behaviour (filters, search index, variants, wishlist, reviews, products per page)
  stays in Webshop Settings.
- **`webshop/webshop/store.py`** (new): `get_current_store()` asks the **`webshop_store_resolver`**
  hook (a callable registered by another app, returning the store name for the current request or
  None; JamesonRGrieve/frappe-public-site-router implements it by host). `overlay_store()` copies
  Webshop Settings and applies a store's fields; `get_store_settings()` / `get_company_store_settings()`
  return the overlaid copy for the request / for a company. No resolver, no request, or no store →
  Webshop Settings unchanged (exact upstream behaviour). `is_multi_store()` = any enabled store.
- **`Website Item.webshop_store`** (new Link field): which store sells the item.
- **Store-scoped coupon codes.** `Coupon Code.webshop_store` (custom Link field, optional; empty =
  every store) makes `coupon_code` unique **per store** instead of site-wide.
  `store.scope_coupon_codes_to_stores()` (after_install + patch `scope_coupon_codes_to_stores`,
  idempotent) adds the field, a Property Setter `unique=0` on `coupon_code`, and drops ERPNext's DB
  unique index on it. `crud_events/coupon_code/validate_store_unique` (Coupon Code `validate`)
  enforces (coupon_code, webshop_store) uniqueness, raising `frappe.UniqueValidationError`; a code
  with no store clashes with the same code on any store. `coupon_name` (the record name) stays
  globally unique, so per-store duplicates need distinct names (the importer uses `<code> - <ABBR>`).
  `store.coupon_store_filters(store)` = the codes a store's cart may apply (its own + store-less).
- **Discount limits** (`webshop/webshop/discounts/`, card 405): what ERPNext's pricing doesn't enforce,
  so mirrored discounts (frappe-idempotent-importer) keep their source's limits. Fields are custom
  fields on ERPNext's records (`discounts/fields.py`, after_install + patch `add_discount_limits`,
  idempotent); child tables are the fork's `Webshop Coupon Customer` / `Webshop Shipping Discount
  Rule|Zone|Item` doctypes.
  - `coupon_limits`: Coupon Code `eligible_customers`, `eligible_emails` (one per line, `*` wildcard;
    matched against the document's `contact_email` and its customer's `email_id`; both lists set → both
    must hold) and `maximum_use_per_customer`; Pricing Rule `maximum_use_per_customer` (coupon-based rules
    only: all the rule's codes together). A use = a submitted Sales Order, or a submitted Sales Invoice
    (not a return) not made from a submitted order with a code of the same limit; cancelled documents
    don't count. Enforced on `validate` of Quotation (the cart's too), Sales Order and Sales Invoice; on
    submit the Coupon Code / Pricing Rule row is locked (`for_update`) before counting. No customer (a
    Quotation to a Lead) + a limit → refused.
  - `shipping`: Pricing Rule `shipping_discount` (Free Shipping | Percentage | Amount),
    `shipping_discount_value`, `_cap`, `max_shipping_charge`, limited to `shipping_discount_rules`
    (Shipping Rules), `_zones` (country, optional state of the shipping address) and `_items` (items +
    their variants, item groups + subgroups: only the share those items bring = charge less the same
    Shipping Rule's charge for the other lines alone). A rule gives it exactly when ERPNext applies the
    rule: listed in an item's `pricing_rules`, or a Transaction rule selected by ERPNext's own
    `get_other_conditions` + qty/amount + dynamic-condition filters; coupon rules only with their code;
    rule currency = document currency. The largest of several is given (never summed).
    `WebshopShippingRule.add_shipping_rule_to_tax_table` writes the charge row already discounted, so
    every total (cart, Quotation, Sales Order, Sales Invoice) carries it.
  - `rule_limits` (card 407; patch `add_rule_limits`, the same `add_discount_limit_fields`): Pricing Rule
    eligibility — `eligible_customers` + `eligible_customer_groups` (a segment: listed customers, or customers
    of a listed group or a group under one), `excluded_customer_groups` (child `Webshop Discount Customer
    Group`), `new_customers_only`, `minimum_customer_orders` (orders counted as `coupon_limits` counts uses,
    `customer_uses(customer, None)`; an invoice's own order isn't an earlier one; Customer locked on submit) —
    and discount limits on price rules: `maximum_discount_amount` (all its lines together, or its transaction
    discount), `spread_discount_amount` (once, across its lines by amount), `maximum_discounted_qty` +
    `discounted_qty_order` (Cheapest First | Dearest First | Each Line), `fixed_price_set_qty|price|order|
    repeat`. A spread amount or sets zero the rule's own discount (ERPNext takes it off each unit and refuses a
    negative total before the hook runs). Enforced on `validate` of Quotation, Sales Order and Sales Invoice
    after ERPNext's pricing (which re-prices on every validate): an ineligible coupon rule refuses the code
    (`CouponNotEligibleError`, the cart too); an ineligible automatic rule is taken off (its line discount,
    others on the line reapplied with `apply_price_discount_rule`; its free items; its transaction discount);
    limits rewrite each line's per-unit `discount_amount` (rounded down) and the totals and payment schedule
    are recalculated. Applied rules are found as ERPNext selects them (`applied`: lines' `pricing_rules`,
    transaction rules via `get_other_conditions`), shared with `shipping`.

## Where it diverges from upstream (in place, guarded, `# fork (multi-store)` / `# fork (discount limits)` comments)

| Upstream site | Change |
|---|---|
| `webshop_settings.get_shopping_cart_settings()` | returns `get_store_settings(...)` — the single seam every cart path reads |
| `shopping_cart/cart.py` | `get_cart_quotation`, `place_order`, `apply_cart_settings`, `get_party` read through `get_shopping_cart_settings()`; `_get_cart_quotation` scopes the reused draft cart to the store's company and creates new carts with the store's company/series; `apply_coupon_code` looks codes up among the cart's store's and store-less codes only (no store → store-less only, i.e. upstream on a single-store site) |
| `product_data_engine/query.py` `ProductQuery.__init__` | store-overlaid settings + `webshop_store` filter |
| `templates/pages/product_search.py` | SQL search and Redisearch results filtered to the store |
| `website_item.WebsiteItem.get_context` | another store's product → `PageDoesNotExistError`; multi-store → `no_cache` |
| `override_doctype/item_group.ItemGroup.get_context` | multi-store → `no_cache` |
| `crud_events/quotation/validate_shopping_cart_items` | cart lines must be the store's Website Items |
| `crud_events/price_list/check_impact_on_cart` | currency change re-validates stores using the price list |
| `override_doctype/payment_request` | success URL + gateway account from the selling company's store |
| `templates/pages/order.py` | `enabled_checkout` from the order company's store |
| `website_item.json` | `webshop_store` field (+ `modified` bump so migrate syncs it) |
| ERPNext `Coupon Code` (not edited; customised from here) | `webshop_store` custom field, `coupon_code` unique → per-store (Property Setter + dropped index + validate hook); eligibility + per-customer limit fields, eligible emails normalised on validate |
| ERPNext `Pricing Rule` (not edited; customised from here) | per-customer limit, shipping discount, eligibility and discount-limit fields, validated (`crud_events/pricing_rule`); enforced on selling documents (`crud_events/sales_document/enforce_rule_limits`) |
| ERPNext `Shipping Rule` (not edited; `override_doctype_class`) | `override_doctype/shipping_rule.WebshopShippingRule`: charge row less the shipping discount |
| `hooks.py` | the overrides and `doc_events` above (Quotation, Sales Order, Sales Invoice, Pricing Rule, Coupon Code) |

**Invariant:** Frappe's rendered-page cache is keyed by route only (`frappe.website.utils.cache_html`),
so any page whose content depends on the store must be `no_cache` in multi-store mode, or one
store's HTML is served on another store's host.

## Testing

`bench --site <site> run-tests --app webshop --module webshop.webshop.doctype.webshop_store.test_webshop_store`
(real DB, ERPNext test fixtures); store-scoped coupons: `...webshop_store.test_coupon_code_store`;
discount limits: `webshop.webshop.discounts.test_coupon_limits`, `...discounts.test_shipping_discounts`,
`...discounts.test_rule_limits`.
Host → store end-to-end tests live in frappe-public-site-router.
Also run upstream's suite to prove no regression with no stores defined. ERPNext's test bootstrap needs a
fresh site (`bench new-site … --install-app erpnext --install-app payments --install-app webshop`, no setup
wizard): on a set-up site it fails creating its master data. A bench: frappe-idempotent-importer's
`tests/e2e/bench.sh` (`WEBSHOP_REPO` = this checkout) stands one up in podman.
