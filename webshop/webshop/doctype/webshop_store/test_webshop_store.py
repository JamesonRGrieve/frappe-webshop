# SPDX-License-Identifier: AGPL-3.0-or-later
"""Webshop Store (fork) against a real test site: the settings overlay, store lookup from the
order a document belongs to (several stores may share a company), the store carried from cart
Quotation to Sales Order, and unchanged upstream behaviour when no store resolver applies.
Host → store resolution is exercised end-to-end by frappe-public-site-router's tests,
the app that implements the webshop_store_resolver hook."""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
from webshop.webshop.store import (
	get_current_store,
	get_document_store_settings,
	is_multi_store,
	overlay_store,
)

test_dependencies = ["Price List", "Customer Group", "Currency Exchange"]

HUB = "_Test 3S Hub Store"


def make_store(name, company, price_list, **extra):
	if frappe.db.exists("Webshop Store", name):
		frappe.delete_doc("Webshop Store", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Webshop Store",
			"store_name": name,
			"enabled": 1,
			"company": company,
			"price_list": price_list,
			"default_customer_group": "_Test Customer Group",
			"quotation_series": "_T-Quotation-",
			**extra,
		}
	).insert()


class TestWebshopStore(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		settings = frappe.get_doc("Webshop Settings")
		settings.update(
			{
				"enabled": 1,
				"company": "_Test Company",
				"default_customer_group": "_Test Customer Group",
				"quotation_series": "_T-Quotation-",
				"price_list": "_Test Price List India",
			}
		)
		settings.save()
		self.store = make_store(HUB, "_Test Company 1", "_Test Price List", enable_checkout=0, show_price=1)

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

	def test_overlay_applies_store_business_fields(self):
		overlaid = overlay_store(frappe.get_single("Webshop Settings"), self.store)
		self.assertEqual(overlaid.company, "_Test Company 1")
		self.assertEqual(overlaid.price_list, "_Test Price List")
		self.assertEqual(overlaid.show_price, 1)
		self.assertEqual(overlaid.webshop_store, HUB)
		# global behaviour still comes from Webshop Settings
		self.assertEqual(overlaid.enabled, 1)

	def test_overlay_does_not_leak_into_cached_settings(self):
		overlay_store(frappe.get_cached_doc("Webshop Settings"), self.store)
		self.assertEqual(frappe.get_cached_doc("Webshop Settings").company, "_Test Company")

	def make_store_quotation(self, store):
		from erpnext.selling.doctype.quotation.test_quotation import make_quotation

		quotation = make_quotation(company="_Test Company", do_not_submit=True)
		quotation.webshop_store = store
		quotation.insert(ignore_permissions=True) if quotation.is_new() else quotation.save()
		return quotation

	def test_document_store_settings(self):
		base = frappe.get_doc("Webshop Settings")
		quotation = self.make_store_quotation(HUB)
		self.assertEqual(get_document_store_settings(base, "Quotation", quotation.name).webshop_store, HUB)
		self.assertIs(get_document_store_settings(base, "Sales Invoice", quotation.name), base)
		quotation.db_set("webshop_store", None)
		self.assertIs(get_document_store_settings(base, "Quotation", quotation.name), base)

	def test_disabled_store_is_not_used_for_documents(self):
		quotation = self.make_store_quotation(HUB)
		frappe.db.set_value("Webshop Store", HUB, "enabled", 0)
		base = frappe.get_doc("Webshop Settings")
		self.assertIs(get_document_store_settings(base, "Quotation", quotation.name), base)

	def test_store_is_carried_to_sales_order(self):
		from erpnext.selling.doctype.quotation.quotation import make_sales_order

		quotation = self.make_store_quotation(HUB)
		quotation.submit()
		self.assertEqual(make_sales_order(quotation.name).webshop_store, HUB)

	def test_no_request_means_upstream_settings(self):
		frappe.local.request = None
		self.assertIsNone(get_current_store())
		settings = get_shopping_cart_settings()
		self.assertEqual(settings.company, "_Test Company")
		self.assertFalse(settings.get("webshop_store"))

	def test_is_multi_store(self):
		self.assertTrue(is_multi_store())
		frappe.db.set_value("Webshop Store", HUB, "enabled", 0)
		self.assertFalse(is_multi_store())

	def test_several_stores_per_company(self):
		# e.g. Stifle Manufacturing and Stifle Apiary both sell as one company
		second = make_store("_Test Second Hub Store", "_Test Company 1", "_Test Price List")
		self.assertEqual(second.company, self.store.company)
		base = frappe.get_doc("Webshop Settings")
		quotation = self.make_store_quotation(second.name)
		self.assertEqual(
			get_document_store_settings(base, "Quotation", quotation.name).webshop_store, second.name
		)
