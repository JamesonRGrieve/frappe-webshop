# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (shipping discounts): a discount's benefit on a Shipping Rule's charge.

A Pricing Rule may give a shipping discount (``shipping_discount``): free shipping, a percentage off it or an amount
off it (``shipping_discount_value``, in the rule's currency); at most ``shipping_discount_cap``; only when the charge
is at most ``max_shipping_charge``. It may be limited to some Shipping Rules (``shipping_discount_rules``),
destinations (``shipping_discount_zones``: a country, or a state of it, of the shipping address) and items
(``shipping_discount_items``: items and their variants, item groups and their subgroups). Limited to items, only
the part of the charge they bring is discounted: the charge less what the same Shipping Rule charges for the
document's other items alone.

A rule gives its shipping discount to a selling document exactly when ERPNext's pricing applies the rule to it: an
item rule ERPNext applied to one of its items, or a transaction rule whose conditions the document meets (company,
customer, groups and territory, dates, quantity and amount, dynamic condition: ERPNext's own checks, reused). A
coupon code's rule only with that code, and only in the rule's currency. Of several, the largest discount is given;
they never add up.

``WebshopShippingRule`` writes the Shipping Rule's charge row already discounted, so every total carries it: the
webshop cart's, and every Quotation, Sales Order and Sales Invoice."""

import frappe
from frappe.utils import flt
from frappe.utils.nestedset import get_descendants_of

from webshop.webshop.discounts.applied import item_rule_names, transaction_rules, with_its_code
from webshop.webshop.discounts.fields import AMOUNT, FREE_SHIPPING, PERCENTAGE

SHIPPING_DISCOUNT_SET = "ifnull(`tabPricing Rule`.shipping_discount, '') != ''"
# Shipping Rule.apply converts its charge to the document's currency at this precision; so does charge_without.
CONVERTED_PRECISION = 2


def discounted_charge(shipping_rule, doc, charge):
	"""``charge`` (``shipping_rule``'s, in ``doc``'s currency) less the largest shipping discount that applies."""
	if shipping_rule.shipping_rule_type != "Selling" or flt(charge) <= 0:
		return charge
	discounts = [discount_off(rule, shipping_rule, doc, flt(charge)) for rule in applicable_rules(doc)]
	best = max(discounts, default=0.0)
	if not best:
		return charge
	return flt(charge - best, frappe.get_precision("Sales Taxes and Charges", "tax_amount"))


def applicable_rules(doc):
	"""The enabled Pricing Rules with a shipping discount ERPNext's pricing applies to ``doc``."""
	if not frappe.db.exists("Pricing Rule", {"shipping_discount": ["is", "set"], "disable": 0}):
		return []
	names = [*item_rule_names(doc), *transaction_rules(doc, SHIPPING_DISCOUNT_SET)]
	rules = [frappe.get_cached_doc("Pricing Rule", name) for name in dict.fromkeys(names)]
	return [
		rule
		for rule in rules
		if rule.get("shipping_discount")
		and not rule.disable
		and (not rule.currency or rule.currency == doc.currency)
		and with_its_code(rule, doc)
	]


def discount_off(rule, shipping_rule, doc, charge):
	"""What ``rule`` takes off ``shipping_rule``'s ``charge`` on ``doc``: nothing outside its limits."""
	limited_to = {row.shipping_rule for row in rule.get("shipping_discount_rules") or []}
	if limited_to and shipping_rule.name not in limited_to:
		return 0.0
	if rule.get("shipping_discount_zones") and not ships_to(rule.shipping_discount_zones, doc):
		return 0.0
	if rule.max_shipping_charge and charge > flt(rule.max_shipping_charge):
		return 0.0
	share = charge
	if rule.get("shipping_discount_items"):
		share = charge - charge_without(shipping_rule, doc, ShippingItems(rule.shipping_discount_items))
	if share <= 0:
		return 0.0
	if rule.shipping_discount == FREE_SHIPPING:
		off = share
	elif rule.shipping_discount == PERCENTAGE:
		off = share * flt(rule.shipping_discount_value) / 100
	elif rule.shipping_discount == AMOUNT:
		off = flt(rule.shipping_discount_value)
	else:
		return 0.0
	if rule.shipping_discount_cap:
		off = min(off, flt(rule.shipping_discount_cap))
	return max(0.0, min(off, share))


def ships_to(zones, doc):
	"""Whether ``doc``'s shipping address is in one of ``zones``. No shipping address: in none."""
	address = doc.get_shipping_address()
	if not address:
		return False
	state = (address.get("state") or "").strip().lower()
	return any(
		zone.country == address.get("country") and (not zone.state or zone.state.strip().lower() == state)
		for zone in zones
	)


class ShippingItems:
	"""The items a shipping discount is limited to: items (a template: each of its variants too) and item
	groups (with every group under them)."""

	def __init__(self, rows):
		self.items = {row.item_code for row in rows if row.item_code}
		self.groups = set()
		for group in {row.item_group for row in rows if row.item_group}:
			self.groups.add(group)
			self.groups.update(get_descendants_of("Item Group", group))

	def includes(self, item_code):
		if item_code in self.items:
			return True
		variant_of, group = frappe.get_cached_value("Item", item_code, ["variant_of", "item_group"])
		return variant_of in self.items or group in self.groups


def charge_without(shipping_rule, doc, items):
	"""What ``shipping_rule`` charges ``doc`` for its lines not of ``items``, alone (nothing when none are left),
	in the document's currency, as ``ShippingRule.apply`` charges it."""
	others = [line for line in doc.get("items") or [] if not items.includes(line.item_code)]
	if not others:
		return 0.0
	match shipping_rule.calculate_based_on:
		case "Net Total":
			amount = shipping_rule.get_shipping_amount_from_rules(
				sum(flt(line.base_net_amount) for line in others)
			)
		case "Net Weight":
			amount = shipping_rule.get_shipping_amount_from_rules(
				sum(flt(line.total_weight) for line in others)
			)
		case _:
			amount = shipping_rule.shipping_amount
	if doc.currency != doc.company_currency:
		amount = flt(amount / doc.conversion_rate, CONVERTED_PRECISION)
	return flt(amount)


def validate_pricing_rule(doc):
	"""Pricing Rule ``validate``: a shipping discount's value fits its kind."""
	kind = doc.get("shipping_discount")
	if not kind:
		return
	value = flt(doc.shipping_discount_value)
	if kind == PERCENTAGE and not 0 < value <= 100:
		frappe.throw(frappe._("A shipping discount percentage is more than 0 and at most 100."))
	if kind == AMOUNT and value <= 0:
		frappe.throw(frappe._("A shipping discount amount is more than 0."))
	if kind == FREE_SHIPPING:
		doc.shipping_discount_value = 0
