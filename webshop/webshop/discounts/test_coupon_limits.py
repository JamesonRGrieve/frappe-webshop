# SPDX-License-Identifier: AGPL-3.0-or-later
"""Coupon limits (fork) against a real test site: eligible customers and emails, and per-customer use limits on a
code and across a rule's codes, enforced on Quotations, Sales Orders, Sales Invoices and the webshop cart."""

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from frappe.tests.utils import FrappeTestCase

from webshop.patches import add_discount_limits
from webshop.webshop.discounts.coupon_limits import (
	CouponLimitReachedError,
	CouponNotEligibleError,
	customer_uses,
	email_matches,
)
from webshop.webshop.doctype.webshop_store.test_coupon_code_store import (
	STORE_A,
	StoreCartTestCase,
	apply_in_store,
	make_coupon,
)

test_dependencies = ["Customer", "Item", "Price List", "Customer Group", "Currency Exchange"]

ALICE, BOB = "_Test Coupon Alice", "_Test Coupon Bob"


def make_rule(**fields):
	return frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": "_Test Coupon Limit Rule",
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"selling": 1,
			"company": "_Test Company",
			"currency": "INR",
			"coupon_code_based": 1,
			**fields,
		}
	).insert()


def make_code(code, rule, **fields):
	return frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"coupon_name": code,
			"coupon_code": code,
			"coupon_type": "Promotional",
			"pricing_rule": rule.name,
			**fields,
		}
	).insert()


def make_customer(name, email=None):
	if not frappe.db.exists("Customer", name):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": "_Test Customer Group",
				"territory": "_Test Territory",
			}
		).insert()
	frappe.db.set_value("Customer", name, "email_id", email)
	return name


def order(customer, code, submit=True, **fields):
	so = make_sales_order(customer=customer, do_not_save=True)
	so.coupon_code = code
	so.update(fields)
	so.insert()
	if submit:
		so.submit()
	return so


def invoice(customer, code, submit=True):
	si = create_sales_invoice(customer=customer, do_not_save=True)
	si.coupon_code = code
	si.insert()
	if submit:
		si.submit()
	return si


class TestCouponLimits(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_customer(ALICE, "alice@example.com")
		make_customer(BOB, "bob@elsewhere.test")
		self.rule = make_rule()

	def tearDown(self):
		frappe.db.rollback()

	# eligibility
	def test_eligible_customers(self):
		make_code("_TFORALICE", self.rule, eligible_customers=[{"customer": ALICE}])
		order(ALICE, "_TFORALICE")
		with self.assertRaises(CouponNotEligibleError):
			order(BOB, "_TFORALICE", submit=False)

	def test_eligible_emails_by_customer_email(self):
		make_code("_TEXAMPLE", self.rule, eligible_emails="*@Example.com")
		order(ALICE, "_TEXAMPLE")
		with self.assertRaises(CouponNotEligibleError):
			order(BOB, "_TEXAMPLE", submit=False)

	def test_eligible_emails_by_contact_email(self):
		make_code("_TEXAMPLE", self.rule, eligible_emails="bob@example.com")
		order(BOB, "_TEXAMPLE", contact_email="bob@example.com")

	def test_customers_and_emails_must_both_hold(self):
		make_code(
			"_TBOTH", self.rule, eligible_customers=[{"customer": BOB}], eligible_emails="*@example.com"
		)
		with self.assertRaises(CouponNotEligibleError):
			order(BOB, "_TBOTH", submit=False)
		with self.assertRaises(CouponNotEligibleError):
			order(ALICE, "_TBOTH", submit=False)

	def test_quotation_is_checked(self):
		make_code("_TFORALICE", self.rule, eligible_customers=[{"customer": ALICE}])
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": BOB,
				"company": "_Test Company",
				"coupon_code": "_TFORALICE",
				"items": [{"item_code": "_Test Item", "qty": 1, "rate": 100}],
			}
		)
		with self.assertRaises(CouponNotEligibleError):
			quotation.insert()

	def test_eligible_emails_are_normalised_and_checked(self):
		code = make_code(
			"_TEMAILS", self.rule, eligible_emails=" A@Example.com \n\n*@example.org\na@example.com"
		)
		self.assertEqual(code.eligible_emails, "a@example.com\n*@example.org")
		code.eligible_emails = "not an address"
		with self.assertRaises(frappe.ValidationError):
			code.save()

	def test_email_patterns(self):
		self.assertTrue(email_matches("*@example.com", "a.b@example.com"))
		self.assertTrue(email_matches("a@example.com", "a@example.com"))
		self.assertFalse(email_matches("*@example.com", "a@example.com.evil"))
		self.assertFalse(email_matches("a.b@example.com", "axb@example.com"))

	# per-customer limits
	def test_once_per_customer(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		order(ALICE, "_TONCE")
		with self.assertRaises(CouponLimitReachedError):
			order(ALICE, "_TONCE", submit=False)
		order(BOB, "_TONCE")

	def test_limit_of_several_uses(self):
		make_code("_TTWICE", self.rule, maximum_use_per_customer=2)
		order(ALICE, "_TTWICE")
		invoice(ALICE, "_TTWICE")
		self.assertEqual(customer_uses(ALICE, ["_TTWICE"]), 2)
		with self.assertRaises(CouponLimitReachedError):
			invoice(ALICE, "_TTWICE", submit=False)

	def test_draft_holds_no_use_but_is_checked_on_submit(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		first = order(ALICE, "_TONCE", submit=False)
		second = order(ALICE, "_TONCE", submit=False)
		first.submit()
		with self.assertRaises(CouponLimitReachedError):
			second.submit()

	def test_cancelled_order_gives_its_use_back(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		order(ALICE, "_TONCE").cancel()
		order(ALICE, "_TONCE")

	def test_invoice_of_an_order_is_the_orders_use(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		so = order(ALICE, "_TONCE")
		si = frappe.get_doc(make_sales_invoice(so.name))
		si.insert()
		si.submit()
		self.assertEqual(customer_uses(ALICE, ["_TONCE"]), 1)

	def test_return_is_neither_a_use_nor_checked(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		si = invoice(ALICE, "_TONCE")
		credit = frappe.get_doc(make_sales_return(si.name))
		credit.insert()
		credit.submit()
		self.assertEqual(customer_uses(ALICE, ["_TONCE"]), 1)

	def test_rule_limit_counts_every_code(self):
		rule = make_rule(title="_Test Rule Wide Limit", maximum_use_per_customer=1)
		make_code("_TCODEA", rule)
		make_code("_TCODEB", rule)
		order(ALICE, "_TCODEA")
		with self.assertRaises(CouponLimitReachedError):
			order(ALICE, "_TCODEB", submit=False)

	def test_limit_needs_a_customer(self):
		make_code("_TONCE", self.rule, maximum_use_per_customer=1)
		lead = frappe.get_doc({"doctype": "Lead", "lead_name": "_Test Coupon Lead"}).insert()
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Lead",
				"party_name": lead.name,
				"company": "_Test Company",
				"coupon_code": "_TONCE",
				"items": [{"item_code": "_Test Item", "qty": 1, "rate": 100}],
			}
		)
		with self.assertRaises(CouponNotEligibleError):
			quotation.insert()

	def test_rule_limit_needs_coupon_codes(self):
		with self.assertRaises(frappe.ValidationError):
			make_rule(title="_Test Automatic Limit", coupon_code_based=0, maximum_use_per_customer=1)

	def test_patch_is_idempotent(self):
		add_discount_limits.execute()
		add_discount_limits.execute()
		for doctype in ("Coupon Code", "Pricing Rule"):
			self.assertTrue(frappe.get_meta(doctype).has_field("maximum_use_per_customer"))
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": "Coupon Code", "fieldname": "eligible_emails"}), 1
		)


class TestCartCouponLimits(StoreCartTestCase):
	def store_code(self, **fields):
		code = make_coupon("_TCARTLIMIT", STORE_A)
		code.update(fields)
		code.save()
		return code

	def test_cart_takes_an_eligible_email(self):
		self.store_code(eligible_emails="*@example.com")
		self.assertEqual(apply_in_store(STORE_A, "_TCARTLIMIT").coupon_code, "_TCARTLIMIT - " + STORE_A)

	def test_cart_refuses_an_ineligible_email(self):
		self.store_code(eligible_emails="someone@elsewhere.test")
		with self.assertRaises(CouponNotEligibleError):
			apply_in_store(STORE_A, "_TCARTLIMIT")

	def test_cart_refuses_a_spent_code(self):
		self.store_code(maximum_use_per_customer=1)
		customer = apply_in_store(STORE_A, "_TCARTLIMIT").party_name
		frappe.set_user("Administrator")
		order(customer, "_TCARTLIMIT - " + STORE_A)
		with self.assertRaises(CouponLimitReachedError):
			apply_in_store(STORE_A, "_TCARTLIMIT")
