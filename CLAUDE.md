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

## Where it diverges from upstream (in place, guarded, `# fork (multi-store)` comments)

| Upstream site | Change |
|---|---|
| `webshop_settings.get_shopping_cart_settings()` | returns `get_store_settings(...)` — the single seam every cart path reads |
| `shopping_cart/cart.py` | `get_cart_quotation`, `place_order`, `apply_cart_settings`, `get_party` read through `get_shopping_cart_settings()`; `_get_cart_quotation` scopes the reused draft cart to the store's company and creates new carts with the store's company/series |
| `product_data_engine/query.py` `ProductQuery.__init__` | store-overlaid settings + `webshop_store` filter |
| `templates/pages/product_search.py` | SQL search and Redisearch results filtered to the store |
| `website_item.WebsiteItem.get_context` | another store's product → `PageDoesNotExistError`; multi-store → `no_cache` |
| `override_doctype/item_group.ItemGroup.get_context` | multi-store → `no_cache` |
| `crud_events/quotation/validate_shopping_cart_items` | cart lines must be the store's Website Items |
| `crud_events/price_list/check_impact_on_cart` | currency change re-validates stores using the price list |
| `override_doctype/payment_request` | success URL + gateway account from the selling company's store |
| `templates/pages/order.py` | `enabled_checkout` from the order company's store |
| `website_item.json` | `webshop_store` field (+ `modified` bump so migrate syncs it) |

**Invariant:** Frappe's rendered-page cache is keyed by route only (`frappe.website.utils.cache_html`),
so any page whose content depends on the store must be `no_cache` in multi-store mode, or one
store's HTML is served on another store's host.

## Testing

`bench --site <site> run-tests --app webshop --module webshop.webshop.doctype.webshop_store.test_webshop_store`
(real DB, ERPNext test fixtures). Host → store end-to-end tests live in frappe-public-site-router.
Also run upstream's suite to prove no regression with no stores defined.
