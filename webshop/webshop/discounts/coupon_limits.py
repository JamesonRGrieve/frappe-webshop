# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (coupon limits): who may use a coupon code, and how often each customer may.

A Coupon Code may name the customers it is for (``eligible_customers``) and the email addresses
(``eligible_emails``: one per line, ``*`` matching anything, as in ``*@example.com``). A document using the code
must be for one of those customers, and its contact email or its customer's email must match one of those
addresses; with both lists set, both must hold.

``maximum_use_per_customer`` on the Coupon Code limits each customer's uses of that code; on its Pricing Rule, each
customer's uses of all the rule's codes together. A use is a submitted Sales Order, or a submitted Sales Invoice
not made from an order with a code of the same limit (that use is the order's); cancelled documents and returns
don't count.

Enforced whenever a Quotation (the webshop cart's included, so a cart can't take a code its customer may not use),
Sales Order or Sales Invoice with a code is validated. A document without a customer (a Quotation to a Lead) can't
use a limited code. On submit the limit's record is locked before counting, so two submissions can't both take a
customer's last use."""

import re

import frappe
from frappe import _

USE_DOCTYPES = ("Sales Order", "Sales Invoice")


class CouponNotEligibleError(frappe.ValidationError):
	pass


class CouponLimitReachedError(frappe.ValidationError):
	pass


def enforce(doc):
	"""Throws unless ``doc`` (a Quotation, Sales Order or Sales Invoice) may use its coupon code."""
	if not doc.get("coupon_code") or doc.get("is_return"):
		return
	coupon = frappe.get_doc("Coupon Code", doc.coupon_code)
	customer = document_customer(doc)
	check_eligibility(coupon, customer, document_emails(doc, customer))

	check_limit(doc, customer, coupon.maximum_use_per_customer, ("Coupon Code", coupon.name), [coupon.name])
	if coupon.pricing_rule:
		rule_limit = frappe.db.get_value("Pricing Rule", coupon.pricing_rule, "maximum_use_per_customer")
		rule_codes = frappe.get_all(
			"Coupon Code", filters={"pricing_rule": coupon.pricing_rule}, pluck="name"
		)
		check_limit(doc, customer, rule_limit, ("Pricing Rule", coupon.pricing_rule), rule_codes)


def document_customer(doc):
	if doc.doctype == "Quotation":
		return doc.party_name if doc.quotation_to == "Customer" else None
	return doc.get("customer")


def document_emails(doc, customer):
	"""The addresses ``doc`` is for: its contact email and its customer's own, lower case."""
	emails = [doc.get("contact_email")]
	if customer:
		emails.append(frappe.db.get_value("Customer", customer, "email_id"))
	return {email.strip().lower() for email in emails if email and email.strip()}


def email_patterns(text):
	"""``eligible_emails`` as patterns: one per non-empty line, lower case."""
	return [line.strip().lower() for line in (text or "").splitlines() if line.strip()]


def email_matches(pattern, email):
	"""Whether ``email`` matches ``pattern``, where ``*`` matches anything (both lower case)."""
	regex = ".*".join(re.escape(part) for part in pattern.split("*"))
	return re.fullmatch(regex, email) is not None


def check_eligibility(coupon, customer, emails):
	customers = {row.customer for row in coupon.get("eligible_customers") or []}
	if customers and customer not in customers:
		frappe.throw(
			_("Coupon code {0} is only for certain customers.").format(frappe.bold(coupon.coupon_code)),
			CouponNotEligibleError,
			title=_("Coupon Not Eligible"),
		)
	patterns = email_patterns(coupon.get("eligible_emails"))
	if patterns and not any(email_matches(pattern, email) for pattern in patterns for email in emails):
		frappe.throw(
			_("Coupon code {0} is only for certain email addresses.").format(frappe.bold(coupon.coupon_code)),
			CouponNotEligibleError,
			title=_("Coupon Not Eligible"),
		)


def check_limit(doc, customer, limit, holder, codes):
	"""Throws when ``customer`` has used ``codes`` (whose limit ``holder``, a (doctype, name), keeps) ``limit``
	times already, not counting ``doc``. An invoice made from an order with one of ``codes`` is that order's use."""
	if not limit or made_from_order_with(doc, codes):
		return
	if not customer:
		frappe.throw(
			_("Coupon code {0} can be used only so many times per customer: it needs a customer.").format(
				frappe.bold(doc.coupon_code)
			),
			CouponNotEligibleError,
			title=_("Coupon Not Eligible"),
		)
	if getattr(doc, "_action", None) == "submit":
		frappe.db.get_value(*holder, "name", for_update=True)
	used = customer_uses(customer, codes, exclude=doc)
	if used >= limit:
		frappe.throw(
			_(
				"Coupon code {0} can be used {1} time(s) per customer, and {2} has used it {3} time(s)."
			).format(frappe.bold(doc.coupon_code), limit, frappe.bold(customer), used),
			CouponLimitReachedError,
			title=_("Coupon Limit Reached"),
		)


def made_from_order_with(doc, codes):
	"""Whether ``doc`` is a Sales Invoice made from a submitted Sales Order with one of ``codes``."""
	if doc.doctype != "Sales Invoice":
		return False
	orders = {item.sales_order for item in doc.get("items") or [] if item.get("sales_order")}
	return bool(orders) and bool(orders_with(orders, codes))


def orders_with(orders, codes):
	return set(
		frappe.get_all(
			"Sales Order",
			filters={"name": ["in", list(orders)], "docstatus": 1, "coupon_code": ["in", codes]},
			pluck="name",
		)
	)


def customer_uses(customer, codes, exclude=None):
	"""How many times ``customer`` has used any of ``codes``: their submitted Sales Orders with one, and their
	submitted Sales Invoices (not returns) with one not made from such an order. ``exclude`` (the document being
	validated) is never counted."""
	found = {}
	for doctype in USE_DOCTYPES:
		filters = {"docstatus": 1, "customer": customer, "coupon_code": ["in", codes]}
		if doctype == "Sales Invoice":
			filters["is_return"] = 0
		if exclude is not None and exclude.doctype == doctype and not exclude.is_new():
			filters["name"] = ["!=", exclude.name]
		found[doctype] = frappe.get_all(doctype, filters=filters, pluck="name")

	invoices = found["Sales Invoice"]
	if invoices:
		lines = frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": ["in", invoices], "parenttype": "Sales Invoice", "sales_order": ["is", "set"]},
			fields=["parent", "sales_order"],
		)
		counted = orders_with({line.sales_order for line in lines}, codes)
		of_orders = {line.parent for line in lines if line.sales_order in counted}
		invoices = [invoice for invoice in invoices if invoice not in of_orders]
	return len(found["Sales Order"]) + len(invoices)


def validate_coupon_code(doc):
	"""Coupon Code ``validate``: its eligible emails, one per line, lower case, each an address or pattern."""
	patterns = email_patterns(doc.get("eligible_emails"))
	invalid = [pattern for pattern in patterns if "@" not in pattern or any(c.isspace() for c in pattern)]
	if invalid:
		frappe.throw(
			_("Not an email address or pattern: {0}").format(", ".join(frappe.bold(p) for p in invalid)),
			title=_("Invalid Eligible Emails"),
		)
	doc.eligible_emails = "\n".join(dict.fromkeys(patterns)) or None


def validate_pricing_rule(doc):
	"""Pricing Rule ``validate``: a per-customer limit counts coupon codes, so it needs a coupon-based rule."""
	if doc.get("maximum_use_per_customer") and not doc.coupon_code_based:
		frappe.throw(
			_(
				"A per-customer use limit counts uses of the rule's coupon codes: make the rule coupon code based."
			),
			title=_("Per-Customer Limit Needs Coupon Codes"),
		)
