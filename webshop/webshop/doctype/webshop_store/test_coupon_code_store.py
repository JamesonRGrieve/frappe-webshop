# SPDX-License-Identifier: AGPL-3.0-or-later
"""Store-scoped coupon codes (fork) against a real test site: codes are unique per store rather than
site-wide, a code with no store applies in (and clashes with) every store, a cart applies only its
own store's codes, and the migration patch is idempotent.

The request → store resolver belongs to another app (frappe-public-site-router), so the cart tests
substitute only that seam; everything else runs against the real database."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.patches import scope_coupon_codes_to_stores as coupon_patch
from webshop.webshop.doctype.webshop_store.test_webshop_store import make_store
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.shopping_cart.cart import apply_coupon_code, update_cart
from webshop.webshop.store import COUPON_TABLE

test_dependencies = ["Price List", "Customer Group", "Currency Exchange", "Item"]

STORE_A = "_Test Coupon Store A"
STORE_B = "_Test Coupon Store B"
CART_USER = "test_coupon_cart_user@example.com"
STORE_RESOLVERS = (
	"webshop.webshop.store.get_current_store",
	"webshop.webshop.crud_events.quotation.validate_shopping_cart_items.get_current_store",
)


def make_coupon(code, store=None, name=None):
	return frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"coupon_name": name or (f"{code} - {store}" if store else code),
			"coupon_type": "Promotional",
			"coupon_code": code,
			"from_external_ecomm_platform": 1,
			"webshop_store": store,
		}
	).insert()


def make_cart(store):
	"""A cart of CART_USER's on ``store``'s host (None: a site without stores) holding one of its items."""
	if not frappe.db.get_value(
		"Item Price", {"price_list": "_Test Price List India", "item_code": "_Test Item"}
	):
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"price_list": "_Test Price List India",
				"item_code": "_Test Item",
				"price_list_rate": 10,
			}
		).insert()
	web_item = frappe.db.get_value("Website Item", {"item_code": "_Test Item"})
	if not web_item:
		web_item = make_website_item(frappe.get_cached_doc("Item", "_Test Item"))[0]
	frappe.db.set_value("Website Item", web_item, "webshop_store", store)
	if not frappe.db.exists("User", CART_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"user_type": "Website User",
				"email": CART_USER,
				"send_welcome_email": 0,
				"first_name": "Coupon Cart",
			}
		).insert(ignore_permissions=True).add_roles("Customer")
	frappe.set_user(CART_USER)
	update_cart("_Test Item", 1)


def apply_in_store(store, code):
	"""``code`` applied to CART_USER's cart on ``store``'s host: its quotation."""
	with patch(STORE_RESOLVERS[0], return_value=store), patch(STORE_RESOLVERS[1], return_value=store):
		frappe.local.shopping_cart_settings = None
		make_cart(store)
		return apply_coupon_code(code, None)


class StoreCartTestCase(FrappeTestCase):
	"""Webshop Settings for _Test Company and two stores on it, every test rolled back."""

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
		frappe.local.shopping_cart_settings = None
		for store in (STORE_A, STORE_B):
			make_store(store, "_Test Company", "_Test Price List India")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")
		frappe.local.shopping_cart_settings = None


class TestCouponCodeStore(StoreCartTestCase):
	@classmethod
	def tearDownClass(cls):
		# the patch tests' DDL commits implicitly, so setUp's stores outlive the rollback
		for store in (STORE_A, STORE_B):
			frappe.delete_doc_if_exists("Webshop Store", store, force=True)
		frappe.db.commit()

	# uniqueness
	def test_same_code_in_different_stores(self):
		make_coupon("_TSAVE10", STORE_A)
		make_coupon("_TSAVE10", STORE_B)
		self.assertEqual(frappe.db.count("Coupon Code", {"coupon_code": "_TSAVE10"}), 2)

	def test_same_code_twice_in_one_store(self):
		make_coupon("_TSAVE10", STORE_A)
		with self.assertRaises(frappe.UniqueValidationError):
			make_coupon("_TSAVE10", STORE_A, name="_TSAVE10 - again")

	def test_store_less_code_clashes_with_any_store(self):
		make_coupon("_TSAVE10", STORE_A)
		with self.assertRaises(frappe.UniqueValidationError):
			make_coupon("_TSAVE10")

	def test_store_code_clashes_with_store_less_code(self):
		make_coupon("_TSAVE10")
		with self.assertRaises(frappe.UniqueValidationError):
			make_coupon("_TSAVE10", STORE_B)

	def test_store_less_codes_stay_unique(self):
		make_coupon("_TSAVE10")
		with self.assertRaises(frappe.UniqueValidationError):
			make_coupon("_TSAVE10", name="_TSAVE10 again")

	def test_resaving_a_code_is_not_a_clash(self):
		coupon = make_coupon("_TSAVE10", STORE_A)
		coupon.description = "changed"
		coupon.save()

	def test_coupon_name_stays_unique(self):
		make_coupon("_TSAVE10", STORE_A, name="_TSAVE10 shared name")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_coupon("_TSAVE20", STORE_B, name="_TSAVE10 shared name")

	# the cart
	def test_cart_applies_its_own_stores_code(self):
		make_coupon("_TSAVE10", STORE_A)
		make_coupon("_TSAVE10", STORE_B)
		self.assertEqual(apply_in_store(STORE_B, "_TSAVE10").coupon_code, f"_TSAVE10 - {STORE_B}")

	def test_cart_rejects_another_stores_code(self):
		make_coupon("_TSAVE10", STORE_A)
		with self.assertRaisesRegex(frappe.ValidationError, "Please enter a valid coupon code"):
			apply_in_store(STORE_B, "_TSAVE10")

	def test_store_less_code_applies_in_every_store(self):
		make_coupon("_TSAVE10")
		self.assertEqual(apply_in_store(STORE_A, "_TSAVE10").coupon_code, "_TSAVE10")
		frappe.set_user("Administrator")
		self.assertEqual(apply_in_store(STORE_B, "_TSAVE10").coupon_code, "_TSAVE10")

	def test_cart_without_store_applies_store_less_code(self):
		# a single-store site: no store resolves, codes have no store — upstream behaviour
		make_coupon("_TSAVE10")
		self.assertEqual(apply_in_store(None, "_TSAVE10").coupon_code, "_TSAVE10")

	def test_referral_sales_partner_still_applies(self):
		make_coupon("_TSAVE10", STORE_A)
		partner = frappe.get_doc(
			{
				"doctype": "Sales Partner",
				"partner_name": "_Test Coupon Partner",
				"commission_rate": 1,
				"territory": "All Territories",
				"referral_code": "_TREF",
			}
		).insert()
		with patch(STORE_RESOLVERS[0], return_value=STORE_A), patch(STORE_RESOLVERS[1], return_value=STORE_A):
			frappe.local.shopping_cart_settings = None
			make_cart(STORE_A)
			quotation = apply_coupon_code("_TSAVE10", "_TREF")
		self.assertEqual(quotation.referral_sales_partner, partner.name)

	# migration
	def test_patch_is_idempotent(self):
		coupon_patch.execute()
		coupon_patch.execute()
		self.assertIsNone(frappe.db.get_column_index(COUPON_TABLE, "coupon_code", unique=True))
		self.assertTrue(frappe.get_meta("Coupon Code").has_field("webshop_store"))
		self.assertEqual(frappe.get_meta("Coupon Code").get_field("coupon_code").unique, 0)
		self.assertEqual(
			frappe.db.count(
				"Property Setter",
				{"doc_type": "Coupon Code", "field_name": "coupon_code", "property": "unique"},
			),
			1,
		)

	def test_patch_drops_a_restored_unique_index(self):
		frappe.db.sql_ddl(f"ALTER TABLE `{COUPON_TABLE}` ADD UNIQUE INDEX coupon_code (coupon_code)")
		self.assertIsNotNone(frappe.db.get_column_index(COUPON_TABLE, "coupon_code", unique=True))
		coupon_patch.execute()
		self.assertIsNone(frappe.db.get_column_index(COUPON_TABLE, "coupon_code", unique=True))
