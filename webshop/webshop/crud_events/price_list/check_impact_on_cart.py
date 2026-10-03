import frappe

from webshop.webshop.doctype.webshop_settings.webshop_settings import (
	validate_cart_settings,
)


def execute(doc, method=None):
	"""
	Check if Price List currency change impacts Webshop Cart
	"""
	if doc.is_new():
		return

	doc_before_save = doc.get_doc_before_save()
	currency_changed = doc.currency != doc_before_save.currency
	affects_cart = doc.name == frappe.get_cached_value("Webshop Settings", None, "price_list")

	if currency_changed and affects_cart:
		validate_cart_settings()

	# fork (multi-store): a store selling in this price list re-checks its own pricing
	if currency_changed:
		for store in frappe.get_all("Webshop Store", filters={"price_list": doc.name}, pluck="name"):
			frappe.get_doc("Webshop Store", store).run_method("validate")
