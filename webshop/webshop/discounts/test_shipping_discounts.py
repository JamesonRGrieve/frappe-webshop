# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shipping discounts (fork) against a real test site: free shipping, a percentage or amount off the Shipping
Rule's charge, its cap and maximum charge, limits to shipping rules, destinations and items, applied when ERPNext's
pricing applies the rule (automatic, by coupon code, item rules) — on Sales Orders and in the webshop cart."""

from unittest.mock import patch

import frappe
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.discounts.coupon_limits import USE_DOCTYPES
from webshop.webshop.doctype.webshop_store.test_coupon_code_store import (
	CART_USER,
	STORE_A,
	STORE_RESOLVERS,
	StoreCartTestCase,
	make_cart,
)
from webshop.webshop.shopping_cart.cart import apply_shipping_rule

test_dependencies = ["Customer", "Item", "Price List", "Customer Group", "Currency Exchange"]

SHIPPING_ACCOUNT = "_Test Account Shipping Charges - _TC"
FLAT, BANDED, OTHER = (
	"_Test Webshop Flat Shipping",
	"_Test Webshop Banded Shipping",
	"_Test Webshop Other Shipping",
)
FLAT_CHARGE = 50


def make_shipping_rule(name, based_on="Fixed", amount=FLAT_CHARGE, bands=()):
	if frappe.db.exists("Shipping Rule", name):
		return frappe.get_doc("Shipping Rule", name)
	return frappe.get_doc(
		{
			"doctype": "Shipping Rule",
			"label": name,
			"shipping_rule_type": "Selling",
			"company": "_Test Company",
			"account": SHIPPING_ACCOUNT,
			"cost_center": "_Test Cost Center - _TC",
			"calculate_based_on": based_on,
			"shipping_amount": amount,
			"conditions": [
				{"from_value": low, "to_value": high, "shipping_amount": charge}
				for low, high, charge in bands
			],
		}
	).insert()


def make_rule(shipping_discount, value=0, **fields):
	return frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": "_Test Shipping Discount",
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 0,
			"selling": 1,
			"company": "_Test Company",
			"currency": "INR",
			"shipping_discount": shipping_discount,
			"shipping_discount_value": value,
			**fields,
		}
	).insert()


def shipping_charge(doc):
	"""The Shipping Rule's charge row (an item tax template may add another row on the same account)."""
	return next(
		row.tax_amount
		for row in doc.taxes
		if row.account_head == SHIPPING_ACCOUNT and row.charge_type == "Actual"
	)


def order(shipping_rule=FLAT, items=None, **fields):
	"""A Sales Order of _Test Customer's (10 x _Test Item at 100 unless ``items``) shipped by ``shipping_rule``."""
	so = make_sales_order(do_not_save=True, **({"item_list": items} if items else {}))
	so.shipping_rule = shipping_rule
	so.update(fields)
	so.insert()
	return so


class TestShippingDiscounts(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_shipping_rule(FLAT)
		make_shipping_rule(OTHER)
		# 0 to 999 costs 30 to ship, 1000 and over 100
		make_shipping_rule(BANDED, "Net Total", bands=[(0, 999, 30), (1000, 0, 100)])

	def tearDown(self):
		frappe.db.rollback()

	def test_no_discount_keeps_the_charge(self):
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)

	def test_free_shipping(self):
		make_rule("Free Shipping")
		so = order()
		self.assertEqual(shipping_charge(so), 0)
		self.assertEqual(so.grand_total, so.net_total)

	def test_percentage_and_its_cap(self):
		rule = make_rule("Percentage", 50)
		self.assertEqual(shipping_charge(order()), 25)
		rule.shipping_discount_cap = 10
		rule.save()
		self.assertEqual(shipping_charge(order()), 40)

	def test_amount_never_below_nothing(self):
		rule = make_rule("Amount", 20)
		self.assertEqual(shipping_charge(order()), 30)
		rule.shipping_discount_value = 80
		rule.save()
		self.assertEqual(shipping_charge(order()), 0)

	def test_maximum_shipping_charge(self):
		rule = make_rule("Free Shipping", max_shipping_charge=40)
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)
		rule.max_shipping_charge = 60
		rule.save()
		self.assertEqual(shipping_charge(order()), 0)

	def test_limited_to_shipping_rules(self):
		make_rule("Free Shipping", shipping_discount_rules=[{"shipping_rule": OTHER}])
		self.assertEqual(shipping_charge(order(FLAT)), FLAT_CHARGE)
		self.assertEqual(shipping_charge(order(OTHER)), 0)

	def test_limited_to_zones(self):
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "_Test Shipping Discount Address",
				"address_type": "Shipping",
				"address_line1": "1 Test Street",
				"city": "Kochi",
				"state": "Kerala",
				"country": "India",
				"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
			}
		).insert()
		rule = make_rule("Free Shipping", shipping_discount_zones=[{"country": "India", "state": "goa"}])
		self.assertEqual(shipping_charge(order(shipping_address_name=address.name)), FLAT_CHARGE)
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)  # no address: in no zone
		rule.shipping_discount_zones[0].state = "KERALA"
		rule.save()
		self.assertEqual(shipping_charge(order(shipping_address_name=address.name)), 0)
		rule.shipping_discount_zones[0].state = None
		rule.save()
		self.assertEqual(shipping_charge(order(shipping_address_name=address.name)), 0)

	def test_limited_to_items_discounts_their_share(self):
		make_rule("Free Shipping", shipping_discount_items=[{"item_code": "_Test Item"}])
		lines = [
			{"item_code": "_Test Item", "qty": 10, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
			{"item_code": "_Test Item 2", "qty": 5, "rate": 100, "warehouse": "_Test Warehouse - _TC"},
		]
		# 1500 costs 100; the other items alone (500) 30: _Test Item's 70 is free
		self.assertEqual(shipping_charge(order(BANDED, lines)), 30)
		# only _Test Item: free; only the other item: nothing off
		self.assertEqual(shipping_charge(order(BANDED, lines[:1])), 0)
		self.assertEqual(shipping_charge(order(BANDED, lines[1:])), 30)

	def test_limited_to_item_groups(self):
		make_rule("Free Shipping", shipping_discount_items=[{"item_group": "All Item Groups"}])
		self.assertEqual(shipping_charge(order()), 0)

	def test_coupon_rule_needs_its_code(self):
		rule = make_rule("Free Shipping", coupon_code_based=1)
		frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": "_TFREESHIP",
				"coupon_code": "_TFREESHIP",
				"coupon_type": "Promotional",
				"pricing_rule": rule.name,
			}
		).insert()
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)
		self.assertEqual(shipping_charge(order(coupon_code="_TFREESHIP")), 0)

	def test_rule_conditions_must_be_met(self):
		make_rule("Free Shipping", min_amt=5000)
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)

	def test_disabled_rule_gives_nothing(self):
		make_rule("Free Shipping", disable=1)
		self.assertEqual(shipping_charge(order()), FLAT_CHARGE)

	def test_largest_discount_alone(self):
		make_rule("Percentage", 20)
		make_rule("Amount", 30)
		self.assertEqual(shipping_charge(order()), 20)

	def test_item_rule_applied_to_an_item(self):
		make_rule("Free Shipping", apply_on="Item Code", items=[{"item_code": "_Test Item"}])
		self.assertEqual(shipping_charge(order()), 0)
		other = [{"item_code": "_Test Item 2", "qty": 1, "rate": 100, "warehouse": "_Test Warehouse - _TC"}]
		self.assertEqual(shipping_charge(order(items=other)), FLAT_CHARGE)

	def test_discount_value_fits_its_kind(self):
		for kind, value in (("Percentage", 0), ("Percentage", 150), ("Amount", 0)):
			with self.assertRaises(frappe.ValidationError):
				make_rule(kind, value)
		self.assertEqual(make_rule("Free Shipping", 5).shipping_discount_value, 0)

	def test_every_selling_document(self):
		make_rule("Free Shipping")
		for doctype in ("Quotation", *USE_DOCTYPES):
			doc = frappe.get_doc(
				{
					"doctype": doctype,
					"company": "_Test Company",
					"customer": "_Test Customer",
					"party_name": "_Test Customer",
					"debit_to": "Debtors - _TC",
					"delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 10),
					"shipping_rule": FLAT,
					"items": [
						{
							"item_code": "_Test Item",
							"qty": 1,
							"rate": 100,
							"warehouse": "_Test Warehouse - _TC",
						}
					],
				}
			).insert()
			self.assertEqual(shipping_charge(doc), 0, doctype)


class TestCartShippingDiscount(StoreCartTestCase):
	def test_cart_charges_discounted_shipping(self):
		make_shipping_rule(FLAT)
		make_rule("Percentage", 50)
		with patch(STORE_RESOLVERS[0], return_value=STORE_A), patch(STORE_RESOLVERS[1], return_value=STORE_A):
			frappe.local.shopping_cart_settings = None
			make_cart(STORE_A)
			apply_shipping_rule(FLAT)
		frappe.set_user("Administrator")
		cart = frappe.get_last_doc("Quotation", {"contact_email": CART_USER, "order_type": "Shopping Cart"})
		self.assertEqual(shipping_charge(cart), FLAT_CHARGE / 2)
