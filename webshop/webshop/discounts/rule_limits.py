# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (rule limits, card 407): who a Pricing Rule is for beyond ERPNext's one customer or customer group, and how
much of it a document gets.

Eligibility: ``eligible_customers`` and ``eligible_customer_groups`` (together a segment: a customer listed, or of
a listed group or a group under one), ``excluded_customer_groups``, ``new_customers_only`` and
``minimum_customer_orders`` (orders as ``coupon_limits`` counts uses: submitted Sales Orders, and submitted Sales
Invoices not made from one; the order an invoice was made from is that purchase, not an earlier one). A document
without a customer is for no one. A coupon code's rule the customer isn't eligible for refuses the code (the cart
too); an automatic one is taken off the document: its discount off its lines (any other rule on them reapplied),
the free items it gave, or the transaction discount it set. A line may then miss a lower-priority rule ERPNext
would have chosen instead: less off, never more.

How much (price discounts only): ``maximum_discounted_qty`` units (the cheapest or dearest first, or so many of each
line) get the discount; ``spread_discount_amount`` is taken off once, spread across the rule's lines in proportion
to their amounts (at most their amount); ``fixed_price_set_qty`` units (the cheapest or dearest first, once or as
many sets as there are) cost ``fixed_price_set_price`` together; ``maximum_discount_amount`` caps what the rule takes
off a document (a transaction rule: its discount). A spread amount or fixed-price sets replace the rule's own
discount, which is kept at nothing (ERPNext would take it off each unit, and refuse a document it takes below
nothing before this runs). A line's discount is then written per unit, rounded down, so a document never gets more
than the rule gives.

Enforced on validate of Quotation (the webshop cart's too), Sales Order and Sales Invoice, after ERPNext's pricing,
which re-prices the document on every validate; the totals (and payment schedule) are then recalculated."""

import math

import frappe
from erpnext.accounts.doctype.pricing_rule.pricing_rule import apply_price_discount_rule
from erpnext.accounts.doctype.pricing_rule.utils import get_applied_pricing_rules
from frappe import _
from frappe.utils import cint, flt
from frappe.utils.nestedset import get_ancestors_of

from webshop.webshop.discounts.applied import item_rule_names, transaction_rules, with_its_code
from webshop.webshop.discounts.coupon_limits import (
	CouponNotEligibleError,
	customer_uses,
	document_customer,
	source_orders,
)
from webshop.webshop.discounts.fields import DEAREST_FIRST, EACH_LINE, UNIT_ORDERS

ELIGIBILITY_TABLES = ("eligible_customers", "eligible_customer_groups", "excluded_customer_groups")
ITEM_LIMITS = ("spread_discount_amount", "maximum_discounted_qty", "fixed_price_set_qty")
PRICE = "Price"
# Rounding a line's discount per unit down: a float a hair under a whole cent is that cent.
ROUNDING_TOLERANCE = 1e-9


def has_eligibility(rule):
	return bool(
		any(rule.get(table) for table in ELIGIBILITY_TABLES)
		or rule.get("new_customers_only")
		or rule.get("minimum_customer_orders")
	)


def has_allotment(rule):
	return bool(flt(rule.get("maximum_discount_amount")) or any(rule.get(field) for field in ITEM_LIMITS))


def enforce(doc):
	"""Applies the eligibility and limits of the rules ERPNext applied to ``doc``."""
	if doc.get("is_return") or doc.get("ignore_pricing_rule"):
		return
	customer = document_customer(doc)
	changed = False
	for name, rows in item_rule_names(doc).items():
		if not frappe.db.exists("Pricing Rule", name):
			continue
		rule = frappe.get_cached_doc("Pricing Rule", name)
		if rule.apply_on == "Transaction" and rule.price_or_product_discount == PRICE:
			continue
		if not is_eligible(rule, doc, customer):
			refuse_code(rule, doc)
			remove(rule, rows, doc)
			changed = True
		elif rule.price_or_product_discount == PRICE and has_allotment(rule):
			changed = allot(rule, rows) or changed
	condition = f"`tabPricing Rule`.price_or_product_discount = '{PRICE}'"
	for name in transaction_rules(doc, condition):
		rule = frappe.get_cached_doc("Pricing Rule", name)
		if (
			not (has_eligibility(rule) or has_allotment(rule))
			or not with_its_code(rule, doc)
			or not gave(rule, doc)
		):
			continue
		if not is_eligible(rule, doc, customer):
			refuse_code(rule, doc)
			doc.additional_discount_percentage = 0
			doc.discount_amount = 0
			changed = True
		elif (cap := flt(rule.get("maximum_discount_amount"))) and flt(doc.discount_amount) > cap:
			doc.additional_discount_percentage = 0
			doc.discount_amount = cap
			changed = True
	if changed:
		doc.calculate_taxes_and_totals()
		if doc.get("payment_schedule"):
			doc.validate_all_documents_schedule()


# -- eligibility -------------------------------------------------------------------------------------------


def is_eligible(rule, doc, customer):
	"""Whether ``customer`` (``doc``'s) may have ``rule``."""
	if not has_eligibility(rule):
		return True
	if not customer:
		return False
	lineage = customer_lineage(customer)
	customers = {row.customer for row in rule.get("eligible_customers") or []}
	groups = {row.customer_group for row in rule.get("eligible_customer_groups") or []}
	if (customers or groups) and customer not in customers and not lineage & groups:
		return False
	if lineage & {row.customer_group for row in rule.get("excluded_customer_groups") or []}:
		return False
	if rule.get("new_customers_only") or rule.get("minimum_customer_orders"):
		orders = orders_before(customer, doc)
		if rule.get("new_customers_only") and orders:
			return False
		if orders < cint(rule.get("minimum_customer_orders")):
			return False
	return True


def customer_lineage(customer):
	"""The customer's group and every group above it."""
	group = frappe.get_cached_value("Customer", customer, "customer_group")
	return {group, *get_ancestors_of("Customer Group", group)} if group else set()


def orders_before(customer, doc):
	"""How many orders ``customer`` placed before ``doc``: not ``doc`` itself, nor the order an invoice was made
	from. On submit the Customer is locked first, so two first orders can't both be a new customer's."""
	if getattr(doc, "_action", None) == "submit":
		frappe.db.get_value("Customer", customer, "name", for_update=True)
	return customer_uses(customer, None, exclude=doc) - len(source_orders(doc))


def refuse_code(rule, doc):
	"""A coupon code's rule the customer isn't eligible for refuses the code."""
	if rule.coupon_code_based:
		frappe.throw(
			_("Coupon code {0} isn't for this customer.").format(frappe.bold(doc.get("coupon_code"))),
			CouponNotEligibleError,
			title=_("Coupon Not Eligible"),
		)


def remove(rule, rows, doc):
	"""Takes ``rule`` off ``doc``: the free items it gave, and its discount off its lines (the others reapplied)."""
	for row in list(doc.get("items") or []):
		if row.get("is_free_item") and rule.name in get_applied_pricing_rules(row.get("pricing_rules")):
			doc.remove(row)
	for row in rows:
		if row.get("is_free_item"):
			continue
		remaining = [name for name in get_applied_pricing_rules(row.pricing_rules) if name != rule.name]
		details = frappe._dict(discount_percentage=0.0, discount_amount=0.0)
		pricing = frappe._dict(
			price_list_rate=row.price_list_rate,
			currency=doc.currency,
			uom=row.uom,
			conversion_factor=row.conversion_factor,
		)
		for name in remaining:
			other = frappe.get_cached_doc("Pricing Rule", name)
			if other.price_or_product_discount == PRICE:
				apply_price_discount_rule(other, details, pricing)
		row.discount_percentage = flt(details.discount_percentage)
		row.discount_amount = flt(details.discount_amount)
		row.rate = flt(row.price_list_rate) - row.discount_amount
		row.pricing_rules = frappe.as_json(remaining) if remaining else ""


def gave(rule, doc):
	"""Whether ``doc``'s transaction discount is the one ``rule`` sets."""
	if rule.rate_or_discount == "Discount Percentage":
		return bool(flt(rule.discount_percentage)) and flt(doc.additional_discount_percentage) == flt(
			rule.discount_percentage
		)
	if rule.rate_or_discount == "Discount Amount":
		return (
			bool(flt(rule.discount_amount))
			and not flt(doc.additional_discount_percentage)
			and flt(doc.discount_amount) == flt(rule.discount_amount)
		)
	return False


# -- how much ----------------------------------------------------------------------------------------------


def allot(rule, rows):
	"""Writes what ``rule`` gives each of its lines under its limits; whether any line changed."""
	lines = [row for row in rows if not row.get("is_free_item") and flt(row.qty) > 0]
	if not lines:
		return False
	prices = [unit_price(row) for row in lines]
	if flt(rule.get("fixed_price_set_qty")):
		given = fixed_sets(rule, lines, prices)
	else:
		counted = discounted_units(rule, lines, prices)
		if amount := flt(rule.get("spread_discount_amount")):
			given = spread(amount, [p * n for p, n in zip(prices, counted, strict=True)])
		else:
			given = [flt(row.discount_amount) * n for row, n in zip(lines, counted, strict=True)]
	given = capped(given, flt(rule.get("maximum_discount_amount")))
	changed = False
	for row, off in zip(lines, given, strict=True):
		per_unit = round_down(off / flt(row.qty), row.precision("discount_amount"))
		if per_unit != flt(row.discount_amount, row.precision("discount_amount")):
			row.discount_percentage = 0
			row.discount_amount = per_unit
			row.rate = unit_price(row) - per_unit
			changed = True
	return changed


def unit_price(row):
	return flt(row.get("rate_with_margin")) or flt(row.price_list_rate)


def round_down(value, precision):
	scale = 10 ** cint(precision)
	return math.floor(max(0.0, value) * scale + ROUNDING_TOLERANCE) / scale


def ordered_units(lines, prices, order):
	"""Each line's units, one entry (line index, price) per unit, the cheapest or dearest first (stable)."""
	units = [
		(index, price)
		for index, (row, price) in enumerate(zip(lines, prices, strict=True))
		for _ in range(int(flt(row.qty)))
	]
	return sorted(units, key=lambda unit: unit[1], reverse=order == DEAREST_FIRST)


def discounted_units(rule, lines, prices):
	"""How many units of each line get the discount: every one, or the rule's maximum quantity."""
	most = flt(rule.get("maximum_discounted_qty"))
	if not most:
		return [flt(row.qty) for row in lines]
	if rule.get("discounted_qty_order") == EACH_LINE:
		return [min(flt(row.qty), most) for row in lines]
	counted = [0.0] * len(lines)
	for index, _price in ordered_units(lines, prices, rule.get("discounted_qty_order"))[: int(most)]:
		counted[index] += 1
	return counted


def spread(amount, bases):
	"""``amount`` once, across ``bases`` (each line's discounted units' amount) in proportion, at most their sum."""
	total = sum(bases)
	if total <= 0:
		return [0.0] * len(bases)
	off = min(amount, total)
	return [off * base / total for base in bases]


def fixed_sets(rule, lines, prices):
	"""What fixed-price sets take off each line: the set units' price less the sets' price, spread over them."""
	size = int(flt(rule.fixed_price_set_qty))
	units = ordered_units(lines, prices, rule.get("fixed_price_set_order"))
	sets = len(units) // size if size else 0
	if not rule.get("fixed_price_set_repeat"):
		sets = min(sets, 1)
	taken = [0.0] * len(lines)
	for index, price in units[: sets * size]:
		taken[index] += price
	off = max(0.0, sum(taken) - sets * flt(rule.fixed_price_set_price))
	return spread(off, taken)


def capped(given, cap):
	"""``given`` scaled down to at most ``cap`` together (0: no cap)."""
	total = sum(given)
	if not cap or total <= cap:
		return given
	return [off * cap / total for off in given]


# -- the rule itself -------------------------------------------------------------------------------------------


def validate_pricing_rule(doc):
	"""Pricing Rule ``validate``: the eligibility and limits fit the rule."""
	if doc.get("discounted_qty_order") and not flt(doc.get("maximum_discounted_qty")):
		doc.discounted_qty_order = None
	if not flt(doc.get("fixed_price_set_qty")):
		doc.fixed_price_set_order, doc.fixed_price_set_price, doc.fixed_price_set_repeat = None, 0, 0
	if doc.get("new_customers_only") and doc.get("minimum_customer_orders"):
		throw(_("A rule for new customers only can't ask for earlier orders."))
	if has_eligibility(doc) and doc.rate_or_discount == "Rate" and not doc.coupon_code_based:
		throw(_("An automatic rule that sets the rate can't be taken back off a line: no eligibility on it."))
	if not has_allotment(doc):
		return
	if doc.price_or_product_discount != PRICE or doc.rate_or_discount == "Rate":
		throw(_("Discount limits limit a discount percentage or amount."))
	if doc.apply_on == "Transaction" and any(doc.get(field) for field in ITEM_LIMITS):
		throw(_("A spread amount, a discounted quantity or fixed-price sets need a rule on items."))
	if flt(doc.get("spread_discount_amount")) or flt(doc.get("fixed_price_set_qty")):
		# They replace the rule's discount, which ERPNext would take off each unit first.
		doc.discount_percentage = doc.discount_amount = 0
	if flt(doc.get("maximum_discounted_qty")) and doc.get("discounted_qty_order") not in (
		*UNIT_ORDERS,
		EACH_LINE,
	):
		throw(_("Say which units a limited quantity discounts."))
	if flt(doc.get("fixed_price_set_qty")):
		if doc.get("fixed_price_set_order") not in UNIT_ORDERS:
			throw(_("Say which units make up a fixed-price set."))
		if flt(doc.get("spread_discount_amount")) or flt(doc.get("maximum_discounted_qty")):
			throw(_("Fixed-price sets replace the rule's discount: no spread amount or discounted quantity."))
		if flt(doc.fixed_price_set_qty) != int(flt(doc.fixed_price_set_qty)):
			throw(_("A fixed-price set is a whole number of units."))


def throw(message):
	frappe.throw(message, title=_("Invalid Discount Limits"))
