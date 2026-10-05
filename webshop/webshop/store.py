# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-store resolution (fork addition).

A site can host several storefronts (``Webshop Store``); a company may sell through several of
them (e.g. one per business line). Which store serves a request is decided by whichever app maps
the site's public hosts to businesses: it registers a ``webshop_store_resolver`` hook (a callable
returning the store name for the current request, or None). The store's business fields are then
overlaid on a copy of Webshop Settings, so every upstream code path that reads cart settings keeps
working unchanged and simply sees that store's values. With no resolver installed, or no store for
this request, nothing is overlaid and Webshop Settings applies exactly as upstream.

Cart quotations record their store (``webshop_store`` on Quotation, carried to the Sales Order),
so documents handled away from the store's host (order pages, payment callbacks) find their store
from the document, never from its company."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ORDER_STORE_FIELD = {
	"fieldname": "webshop_store",
	"fieldtype": "Link",
	"options": "Webshop Store",
	"label": "Webshop Store",
	"insert_after": "order_type",
	"read_only": 1,
	"description": "The webshop storefront this order was placed through.",
}
ORDER_DOCTYPES = ("Quotation", "Sales Order")

STORE_FIELDS = (
	"company",
	"price_list",
	"default_customer_group",
	"quotation_series",
	"save_quotations_as_draft",
	"enable_checkout",
	"payment_success_url",
	"payment_gateway_account",
	"show_price",
	"hide_price_for_guest",
	"show_stock_availability",
	"allow_items_not_in_stock",
	"show_quantity_in_website",
	"show_contact_us_button",
)


def get_current_store():
	"""The enabled store serving this request, or None."""
	if not getattr(frappe.local, "request", None):
		return None
	for resolver in frappe.get_hooks("webshop_store_resolver"):
		store = frappe.get_attr(resolver)()
		if store and frappe.db.get_value("Webshop Store", store, "enabled"):
			return store
	return None


def is_multi_store():
	"""True once any store exists — store-scoped pages then must not be served from a
	path-keyed HTML cache shared across hosts."""
	return bool(frappe.db.exists("Webshop Store", {"enabled": 1}))


def overlay_store(settings, store):
	"""A copy of ``settings`` (Webshop Settings) with ``store``'s business fields applied."""
	overlaid = frappe.copy_doc(settings, ignore_no_copy=True)
	overlaid.name = settings.name
	for field in STORE_FIELDS:
		overlaid.set(field, store.get(field))
	overlaid.webshop_store = store.name
	return overlaid


def get_store_settings(settings):
	"""``settings`` as the current request's store sees them (unchanged when no store applies)."""
	store_name = get_current_store()
	if not store_name:
		return settings
	return overlay_store(settings, frappe.get_cached_doc("Webshop Store", store_name))


def get_document_store_settings(settings, doctype, name):
	"""``settings`` as the store that took order ``doctype``/``name`` (a cart Quotation or its Sales
	Order) sees them — for documents handled outside that store's host, e.g. a gateway callback.
	Unchanged when the order has no store or its store is disabled."""
	store_name = frappe.db.get_value(doctype, name, "webshop_store") if doctype in ORDER_DOCTYPES else None
	if not (store_name and frappe.db.get_value("Webshop Store", store_name, "enabled")):
		return settings
	return overlay_store(settings, frappe.get_cached_doc("Webshop Store", store_name))


def add_order_store_fields():
	"""The ``webshop_store`` link on Quotation and Sales Order (install + patch)."""
	create_custom_fields({doctype: [ORDER_STORE_FIELD] for doctype in ORDER_DOCTYPES})
