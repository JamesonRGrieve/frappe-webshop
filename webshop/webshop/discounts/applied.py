# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): which Pricing Rules ERPNext's pricing applies to a selling document, as it selects them,
for the limits it doesn't enforce itself (``shipping``, ``rule_limits``)."""

import frappe
from erpnext.accounts.doctype.pricing_rule.utils import (
	filter_pricing_rule_based_on_condition,
	filter_pricing_rules_for_qty_amount,
	get_applied_pricing_rules,
	get_other_conditions,
)


def transaction_rules(doc, condition):
	"""The enabled transaction rules matching ``condition`` (SQL on `tabPricing Rule`) whose conditions ``doc``
	meets, as ERPNext selects transaction rules (``apply_pricing_rule_on_transaction``)."""
	values = {}
	conditions = get_other_conditions(
		f"`tabPricing Rule`.apply_on = 'Transaction' and {condition}", values, doc
	)
	rules = frappe.db.sql(
		f"select `tabPricing Rule`.* from `tabPricing Rule` where {conditions} and `tabPricing Rule`.disable = 0",
		values,
		as_dict=True,
	)
	rules = filter_pricing_rules_for_qty_amount(doc.total_qty, doc.total, rules)
	return [rule.name for rule in filter_pricing_rule_based_on_condition(rules, doc)]


def item_rule_names(doc):
	"""The rules ERPNext applied to ``doc``'s lines (their ``pricing_rules``), each with its lines."""
	found = {}
	for row in doc.get("items") or []:
		for name in get_applied_pricing_rules(row.get("pricing_rules")):
			found.setdefault(name, []).append(row)
	return found


def with_its_code(rule, doc):
	"""A coupon code's rule applies only with one of its codes."""
	if not rule.coupon_code_based:
		return True
	code = doc.get("coupon_code")
	return bool(code) and frappe.db.get_value("Coupon Code", code, "pricing_rule") == rule.name
