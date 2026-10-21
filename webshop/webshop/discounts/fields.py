# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): the fields the fork adds to ERPNext's Coupon Code and Pricing Rule, created on
install and by the ``add_discount_limits`` patch (idempotent: ``create_custom_fields`` updates them)."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FREE_SHIPPING, PERCENTAGE, AMOUNT = "Free Shipping", "Percentage", "Amount"
SHIPPING_DISCOUNTS = (FREE_SHIPPING, PERCENTAGE, AMOUNT)

PER_CUSTOMER_DESCRIPTION = (
	"0: no limit. A use is a submitted Sales Order, or a submitted Sales Invoice not made from an order "
	"with the code; cancelled documents and returns don't count."
)

COUPON_CODE_FIELDS = [
	{
		"fieldname": "maximum_use_per_customer",
		"fieldtype": "Int",
		"label": "Maximum Use per Customer",
		"insert_after": "used",
		"non_negative": 1,
		"description": "How many times each customer may use this code. " + PER_CUSTOMER_DESCRIPTION,
	},
	{
		"fieldname": "webshop_eligibility_section",
		"fieldtype": "Section Break",
		"label": "Eligibility",
		"insert_after": "amended_from",
		"collapsible": 1,
	},
	{
		"fieldname": "eligible_customers",
		"fieldtype": "Table MultiSelect",
		"label": "Eligible Customers",
		"options": "Webshop Coupon Customer",
		"insert_after": "webshop_eligibility_section",
		"description": "Only these customers may use the code. Empty: every customer.",
	},
	{
		"fieldname": "eligible_emails",
		"fieldtype": "Small Text",
		"label": "Eligible Emails",
		"insert_after": "eligible_customers",
		"description": "One address per line; * matches anything (*@example.com). Only an order or invoice whose "
		"contact email, or whose customer's email, matches one may use the code. Empty: any address.",
	},
]

PRICING_RULE_FIELDS = [
	{
		"fieldname": "maximum_use_per_customer",
		"fieldtype": "Int",
		"label": "Maximum Use per Customer",
		"insert_after": "coupon_code_based",
		"non_negative": 1,
		"depends_on": "eval:doc.coupon_code_based",
		"description": "How many times each customer may use any of this rule's coupon codes, together. "
		+ PER_CUSTOMER_DESCRIPTION,
	},
	{
		"fieldname": "webshop_shipping_section",
		"fieldtype": "Section Break",
		"label": "Shipping Discount",
		"insert_after": "for_price_list",
		"collapsible": 1,
	},
	{
		"fieldname": "shipping_discount",
		"fieldtype": "Select",
		"label": "Shipping Discount",
		"options": "\n" + "\n".join(SHIPPING_DISCOUNTS),
		"insert_after": "webshop_shipping_section",
		"description": "Taken off the charge of the document's Shipping Rule when this rule applies to it. When "
		"several rules give one, the largest is given.",
	},
	{
		"fieldname": "shipping_discount_value",
		"fieldtype": "Float",
		"label": "Shipping Discount Value",
		"insert_after": "shipping_discount",
		"depends_on": "eval:['Percentage', 'Amount'].includes(doc.shipping_discount)",
		"description": "The percentage, or the amount in the rule's currency, off the shipping charge.",
	},
	{
		"fieldname": "shipping_discount_cap",
		"fieldtype": "Currency",
		"label": "Shipping Discount Cap",
		"options": "currency",
		"insert_after": "shipping_discount_value",
		"depends_on": "shipping_discount",
		"description": "At most this much off the shipping charge. 0: no cap.",
	},
	{
		"fieldname": "max_shipping_charge",
		"fieldtype": "Currency",
		"label": "Maximum Shipping Charge",
		"options": "currency",
		"insert_after": "shipping_discount_cap",
		"depends_on": "shipping_discount",
		"description": "Only a shipping charge of at most this much is discounted. 0: any charge.",
	},
	{
		"fieldname": "webshop_shipping_column",
		"fieldtype": "Column Break",
		"insert_after": "max_shipping_charge",
	},
	{
		"fieldname": "shipping_discount_rules",
		"fieldtype": "Table MultiSelect",
		"label": "Shipping Rules",
		"options": "Webshop Shipping Discount Rule",
		"insert_after": "webshop_shipping_column",
		"depends_on": "shipping_discount",
		"description": "Only on these shipping methods. Empty: every one.",
	},
	{
		"fieldname": "shipping_discount_zones",
		"fieldtype": "Table",
		"label": "Shipping Zones",
		"options": "Webshop Shipping Discount Zone",
		"insert_after": "shipping_discount_rules",
		"depends_on": "shipping_discount",
		"description": "Only to these destinations (the shipping address). Empty: everywhere.",
	},
	{
		"fieldname": "shipping_discount_items",
		"fieldtype": "Table",
		"label": "Shipping Items",
		"options": "Webshop Shipping Discount Item",
		"insert_after": "shipping_discount_zones",
		"depends_on": "shipping_discount",
		"description": "Only the part of the charge these items bring: the charge less what the same Shipping "
		"Rule charges for the other items alone. Empty: the whole charge.",
	},
]


def add_discount_limit_fields():
	"""Coupon Code's per-customer limit and eligibility, and Pricing Rule's per-customer limit and shipping
	discount (install + patch; idempotent)."""
	create_custom_fields(
		{"Coupon Code": COUPON_CODE_FIELDS, "Pricing Rule": PRICING_RULE_FIELDS}, update=True
	)
