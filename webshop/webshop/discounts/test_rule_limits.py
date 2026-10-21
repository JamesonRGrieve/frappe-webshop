# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule limits (fork) against a real test site: a Pricing Rule's eligibility (segments of customers and customer
groups, excluded groups, new and returning customers) and its discount limits (a cap, an amount spread across
lines, a discounted quantity, fixed-price sets), on Quotations, Sales Orders, Sales Invoices and the webshop
cart."""

from unittest.mock import patch

import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from frappe.tests.utils import FrappeTestCase

from webshop.patches import add_rule_limits
from webshop.webshop.discounts.coupon_limits import CouponNotEligibleError
from webshop.webshop.discounts.fields import CHEAPEST_FIRST, DEAREST_FIRST, EACH_LINE
from webshop.webshop.discounts.rule_limits import capped, round_down, spread
from webshop.webshop.discounts.test_coupon_limits import ALICE, make_code, make_customer
from webshop.webshop.doctype.webshop_store.test_coupon_code_store import (
	STORE_A,
	STORE_RESOLVERS,
	StoreCartTestCase,
	apply_in_store,
	make_cart,
	make_coupon,
)

test_dependencies = ["Customer", "Item", "Price List", "Customer Group", "Currency Exchange"]

WAREHOUSE = "_Test Warehouse - _TC"
ITEM, OTHER_ITEM = "_Test Item", "_Test Item 2"
OWN_GROUP, OTHER_GROUP = "_Test Customer Group", "_Test Customer Group 1"


def make_rule(**fields):
	"""An automatic 10% off _Test Item and _Test Item 2 for _Test Company, with ``fields``."""
	return frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": "_Test Rule Limits",
			"apply_on": "Item Code",
			"items": [{"item_code": ITEM}, {"item_code": OTHER_ITEM}],
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"selling": 1,
			"company": "_Test Company",
			"currency": "INR",
			**fields,
		}
	).insert()


def line(item, qty, price):
	return {"item_code": item, "qty": qty, "price_list_rate": price, "rate": price, "warehouse": WAREHOUSE}


TWO_LINES = [line(ITEM, 2, 100), line(OTHER_ITEM, 2, 50)]


def order(lines=None, customer="_Test Customer", submit=False, **fields):
	"""A Sales Order of ``lines`` (10 x _Test Item at 100 unless given)."""
	so = make_sales_order(customer=customer, item_list=lines or [line(ITEM, 10, 100)], do_not_save=True)
	so.update(fields)
	so.insert()
	if submit:
		so.submit()
	return so


def unit_discounts(doc):
	return [row.discount_amount for row in doc.items]


class TestRuleEligibility(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_eligible_customer_groups(self):
		rule = make_rule(eligible_customer_groups=[{"customer_group": OTHER_GROUP}])
		self.assertEqual(order().net_total, 1000)
		rule.append("eligible_customer_groups", {"customer_group": OWN_GROUP})
		rule.save()
		self.assertEqual(order().net_total, 900)

	def test_group_above_the_customers(self):
		make_rule(eligible_customer_groups=[{"customer_group": "All Customer Groups"}])
		self.assertEqual(order().net_total, 900)

	def test_segment_of_customers_and_groups(self):
		make_rule(
			eligible_customers=[{"customer": "_Test Customer"}],
			eligible_customer_groups=[{"customer_group": OTHER_GROUP}],
		)
		self.assertEqual(order().net_total, 900)
		self.assertEqual(order(customer="_Test Customer 1").net_total, 1000)

	def test_excluded_customer_groups(self):
		make_rule(excluded_customer_groups=[{"customer_group": OWN_GROUP}])
		so = order()
		self.assertEqual((so.net_total, so.items[0].pricing_rules), (1000, ""))

	def test_new_customers_only(self):
		make_customer(ALICE)
		make_rule(new_customers_only=1)
		first = order(customer=ALICE, submit=True)
		self.assertEqual(first.net_total, 900)
		invoice = frappe.get_doc(make_sales_invoice(first.name))
		invoice.insert()
		self.assertEqual(invoice.net_total, 900, "the invoice of the first order is that order")
		self.assertEqual(order(customer=ALICE).net_total, 1000)

	def test_minimum_customer_orders(self):
		make_customer(ALICE)
		make_rule(minimum_customer_orders=1)
		self.assertEqual(order(customer=ALICE, submit=True).net_total, 1000)
		self.assertEqual(order(customer=ALICE).net_total, 900)

	def test_cancelled_order_is_no_order(self):
		make_customer(ALICE)
		make_rule(minimum_customer_orders=1)
		order(customer=ALICE, submit=True).cancel()
		self.assertEqual(order(customer=ALICE).net_total, 1000)

	def test_coupon_rule_refuses_its_code(self):
		rule = make_rule(
			apply_on="Transaction",
			items=[],
			coupon_code_based=1,
			excluded_customer_groups=[{"customer_group": OWN_GROUP}],
		)
		make_code("_TRULEGROUP", rule)
		with self.assertRaises(CouponNotEligibleError):
			order(coupon_code="_TRULEGROUP")

	def test_automatic_transaction_rule_taken_off(self):
		make_rule(apply_on="Transaction", items=[], excluded_customer_groups=[{"customer_group": OWN_GROUP}])
		so = order()
		self.assertEqual(
			(so.additional_discount_percentage, so.discount_amount, so.grand_total), (0, 0, 1000)
		)

	def test_document_without_customer_is_for_no_one(self):
		make_rule(eligible_customer_groups=[{"customer_group": "All Customer Groups"}])
		lead = frappe.get_doc({"doctype": "Lead", "lead_name": "_Test Rule Limits Lead"}).insert()
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Lead",
				"party_name": lead.name,
				"company": "_Test Company",
				"items": [line(ITEM, 1, 100)],
			}
		).insert()
		self.assertEqual(quotation.net_total, 100)

	def test_invalid_eligibility(self):
		with self.assertRaises(frappe.ValidationError):
			make_rule(new_customers_only=1, minimum_customer_orders=2)
		with self.assertRaises(frappe.ValidationError):
			make_rule(rate_or_discount="Rate", rate=50, minimum_customer_orders=1)


class TestRuleAllotment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_unlimited_rule_is_erpnexts(self):
		make_rule()
		so = order(TWO_LINES)
		self.assertEqual((unit_discounts(so), so.net_total), ([10, 5], 270))

	def test_cap_on_lines(self):
		make_rule(maximum_discount_amount=15)
		so = order(TWO_LINES)
		self.assertEqual((unit_discounts(so), so.net_total), ([5, 2.5], 285))

	def test_cap_on_a_transaction_rule(self):
		make_rule(apply_on="Transaction", items=[], maximum_discount_amount=50)
		so = order()
		self.assertEqual((so.discount_amount, so.grand_total), (50, 950))

	def test_discounted_quantity(self):
		rule = make_rule(maximum_discounted_qty=2, discounted_qty_order=CHEAPEST_FIRST)
		self.assertEqual(order(TWO_LINES).net_total, 290)
		for units, net in ((DEAREST_FIRST, 280), (EACH_LINE, 270)):
			rule.discounted_qty_order = units
			rule.save()
			self.assertEqual(order(TWO_LINES).net_total, net, units)
		rule.discounted_qty_order = EACH_LINE
		rule.maximum_discounted_qty = 1
		rule.save()
		self.assertEqual(unit_discounts(order(TWO_LINES)), [5, 2.5])

	def test_spread_amount(self):
		rule = make_rule(rate_or_discount="Discount Amount", discount_amount=30, spread_discount_amount=30)
		self.assertEqual((rule.discount_amount, rule.discount_percentage), (0, 0), "it replaces the rule's")
		so = order(TWO_LINES)
		self.assertEqual((unit_discounts(so), so.net_total), ([10, 5], 270))

	def test_spread_amount_at_most_the_lines(self):
		make_rule(spread_discount_amount=500)
		self.assertEqual(order(TWO_LINES).net_total, 0)

	def test_spread_amount_with_a_discounted_quantity(self):
		make_rule(spread_discount_amount=30, maximum_discounted_qty=2, discounted_qty_order=DEAREST_FIRST)
		so = order(TWO_LINES)
		self.assertEqual((unit_discounts(so), so.net_total), ([15, 0], 270))

	def test_fixed_price_set(self):
		rule = make_rule(
			discount_percentage=0,
			fixed_price_set_qty=3,
			fixed_price_set_price=200,
			fixed_price_set_order=CHEAPEST_FIRST,
		)
		self.assertEqual(order(TWO_LINES).net_total, 300, "the cheapest three are worth 200: nothing off")
		rule.fixed_price_set_order = DEAREST_FIRST
		rule.save()
		so = order(TWO_LINES)
		self.assertEqual((unit_discounts(so), so.net_total), ([20, 5], 250))

	def test_repeated_fixed_price_sets(self):
		rule = make_rule(
			discount_percentage=0,
			fixed_price_set_qty=2,
			fixed_price_set_price=120,
			fixed_price_set_order=DEAREST_FIRST,
		)
		self.assertEqual(order(TWO_LINES).net_total, 220, "one set of the two dearest")
		rule.fixed_price_set_repeat = 1
		rule.save()
		self.assertEqual(order(TWO_LINES).net_total, 240, "two sets")

	def test_every_selling_document(self):
		make_rule(maximum_discount_amount=15)
		for doctype in ("Quotation", "Sales Invoice"):
			doc = frappe.get_doc(
				{
					"doctype": doctype,
					"company": "_Test Company",
					"customer": "_Test Customer",
					"party_name": "_Test Customer",
					"debit_to": "Debtors - _TC",
					"items": TWO_LINES,
				}
			).insert()
			self.assertEqual(doc.net_total, 285, doctype)

	def test_invalid_limits(self):
		for fields in (
			{"maximum_discounted_qty": 2},
			{"apply_on": "Transaction", "items": [], "spread_discount_amount": 5},
			{
				"fixed_price_set_qty": 2,
				"fixed_price_set_price": 10,
				"fixed_price_set_order": CHEAPEST_FIRST,
				"spread_discount_amount": 5,
			},
			{
				"apply_on": "Transaction",
				"items": [],
				"maximum_discounted_qty": 2,
				"discounted_qty_order": EACH_LINE,
			},
			{"fixed_price_set_qty": 3, "fixed_price_set_price": 10},
			{
				"fixed_price_set_qty": 2.5,
				"fixed_price_set_price": 10,
				"fixed_price_set_order": CHEAPEST_FIRST,
			},
			{"rate_or_discount": "Rate", "rate": 50, "maximum_discount_amount": 5},
		):
			with self.assertRaises(frappe.ValidationError, msg=str(fields)):
				make_rule(**fields)

	def test_pure_arithmetic(self):
		self.assertEqual(round_down(8.3333, 2), 8.33)
		self.assertEqual(round_down(4.999999999999, 2), 5.0)
		self.assertEqual(spread(30, [200, 100]), [20, 10])
		self.assertEqual(spread(500, [200, 100]), [200, 100])
		self.assertEqual(capped([20, 10], 15), [10, 5])
		self.assertEqual(capped([20, 10], 0), [20, 10])

	def test_patch_is_idempotent(self):
		add_rule_limits.execute()
		add_rule_limits.execute()
		meta = frappe.get_meta("Pricing Rule")
		for field in ("eligible_customer_groups", "maximum_discount_amount", "fixed_price_set_qty"):
			self.assertTrue(meta.has_field(field), field)
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": "Pricing Rule", "fieldname": "minimum_customer_orders"}), 1
		)


class TestCartRuleLimits(StoreCartTestCase):
	def cart_line(self):
		"""The first line of CART_USER's cart on store A's host."""
		with patch(STORE_RESOLVERS[0], return_value=STORE_A), patch(STORE_RESOLVERS[1], return_value=STORE_A):
			frappe.local.shopping_cart_settings = None
			make_cart(STORE_A)
		frappe.set_user("Administrator")
		return frappe.get_last_doc("Quotation", {"order_type": "Shopping Cart"}).items[0]

	def test_cart_leaves_out_a_rule_for_other_groups(self):
		rule = make_rule(eligible_customer_groups=[{"customer_group": OTHER_GROUP}])
		self.assertEqual(self.cart_line().discount_amount, 0)
		rule.append("eligible_customer_groups", {"customer_group": OWN_GROUP})
		rule.save()
		self.assertEqual(self.cart_line().discount_amount, 1)

	def test_cart_refuses_a_code_for_other_groups(self):
		rule = make_rule(
			apply_on="Transaction",
			items=[],
			coupon_code_based=1,
			eligible_customer_groups=[{"customer_group": OTHER_GROUP}],
		)
		code = make_coupon("_TCARTGROUP", STORE_A)
		code.pricing_rule = rule.name
		code.save()
		with self.assertRaises(CouponNotEligibleError):
			apply_in_store(STORE_A, "_TCARTGROUP")
