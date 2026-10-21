# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): the fields the fork adds to ERPNext's Coupon Code and Pricing Rule, created on
install and by the ``add_discount_limits`` patch (idempotent: ``create_custom_fields`` updates them)."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FREE_SHIPPING, PERCENTAGE, AMOUNT = "Free Shipping", "Percentage", "Amount"
SHIPPING_DISCOUNTS = (FREE_SHIPPING, PERCENTAGE, AMOUNT)
# Which units a rule's limited quantity, or its fixed-price sets, take (card 407).
CHEAPEST_FIRST, DEAREST_FIRST, EACH_LINE = "Cheapest First", "Dearest First", "Each Line"
UNIT_ORDERS = (CHEAPEST_FIRST, DEAREST_FIRST)

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

# Card 407: who a rule is for beyond ERPNext's one customer or group, and how much of it a document gets.
PRICING_RULE_ELIGIBILITY_FIELDS = [
	{
		"fieldname": "webshop_eligibility_section",
		"fieldtype": "Section Break",
		"label": "Eligibility",
		"insert_after": "supplier_group",
		"collapsible": 1,
		"depends_on": "selling",
	},
	{
		"fieldname": "eligible_customers",
		"fieldtype": "Table MultiSelect",
		"label": "Eligible Customers",
		"options": "Webshop Coupon Customer",
		"insert_after": "webshop_eligibility_section",
		"description": "Only these customers, and the customers of the Eligible Customer Groups (a segment). Both "
		"empty: every customer.",
	},
	{
		"fieldname": "eligible_customer_groups",
		"fieldtype": "Table MultiSelect",
		"label": "Eligible Customer Groups",
		"options": "Webshop Discount Customer Group",
		"insert_after": "eligible_customers",
		"description": "Only customers of these groups (or groups under them), and the Eligible Customers.",
	},
	{
		"fieldname": "excluded_customer_groups",
		"fieldtype": "Table MultiSelect",
		"label": "Excluded Customer Groups",
		"options": "Webshop Discount Customer Group",
		"insert_after": "eligible_customer_groups",
		"description": "Never customers of these groups (or groups under them).",
	},
	{
		"fieldname": "webshop_eligibility_column",
		"fieldtype": "Column Break",
		"insert_after": "excluded_customer_groups",
	},
	{
		"fieldname": "new_customers_only",
		"fieldtype": "Check",
		"label": "New Customers Only",
		"insert_after": "webshop_eligibility_column",
		"description": "Only customers with no order yet. An order: a submitted Sales Order, or a submitted Sales "
		"Invoice not made from an order; cancelled documents and returns don't count.",
	},
	{
		"fieldname": "minimum_customer_orders",
		"fieldtype": "Int",
		"label": "Minimum Customer Orders",
		"insert_after": "new_customers_only",
		"non_negative": 1,
		"depends_on": "eval:!doc.new_customers_only",
		"description": "Only customers with at least this many orders already. 0: any customer.",
	},
]

PRICING_RULE_ALLOTMENT_FIELDS = [
	{
		"fieldname": "webshop_limits_section",
		"fieldtype": "Section Break",
		"label": "Discount Limits",
		"insert_after": "shipping_discount_items",
		"collapsible": 1,
		"depends_on": "eval:doc.price_or_product_discount == 'Price'",
	},
	{
		"fieldname": "maximum_discount_amount",
		"fieldtype": "Currency",
		"label": "Maximum Discount Amount",
		"options": "currency",
		"insert_after": "webshop_limits_section",
		"non_negative": 1,
		"description": "At most this much off a document, all its lines together (a transaction rule: off the "
		"document). 0: no cap.",
	},
	{
		"fieldname": "spread_discount_amount",
		"fieldtype": "Currency",
		"label": "Spread Discount Amount",
		"options": "currency",
		"insert_after": "maximum_discount_amount",
		"non_negative": 1,
		"depends_on": "eval:doc.apply_on != 'Transaction'",
		"description": "This much off once per document, spread across the lines the rule applies to in "
		"proportion to their amounts (at most their amount), instead of the rule's discount off each unit. "
		"0: none.",
	},
	{
		"fieldname": "maximum_discounted_qty",
		"fieldtype": "Float",
		"label": "Maximum Discounted Quantity",
		"insert_after": "spread_discount_amount",
		"non_negative": 1,
		"depends_on": "eval:doc.apply_on != 'Transaction'",
		"description": "At most this many units get the discount. 0: every unit.",
	},
	{
		"fieldname": "discounted_qty_order",
		"fieldtype": "Select",
		"label": "Discounted Units",
		"options": "\n" + "\n".join((*UNIT_ORDERS, EACH_LINE)),
		"insert_after": "maximum_discounted_qty",
		"depends_on": "maximum_discounted_qty",
		"description": "Which units: the cheapest or dearest first (all lines together), or at most that many of "
		"each line.",
	},
	{
		"fieldname": "webshop_limits_column",
		"fieldtype": "Column Break",
		"insert_after": "discounted_qty_order",
	},
	{
		"fieldname": "fixed_price_set_qty",
		"fieldtype": "Float",
		"label": "Fixed Price Set Quantity",
		"insert_after": "webshop_limits_column",
		"non_negative": 1,
		"depends_on": "eval:doc.apply_on != 'Transaction'",
		"description": 'So many units of the rule\'s items together for the Fixed Price Set Price ("3 for 10"), '
		"instead of the rule's discount. 0: no set.",
	},
	{
		"fieldname": "fixed_price_set_price",
		"fieldtype": "Currency",
		"label": "Fixed Price Set Price",
		"options": "currency",
		"insert_after": "fixed_price_set_qty",
		"non_negative": 1,
		"depends_on": "fixed_price_set_qty",
		"description": "What one set costs.",
	},
	{
		"fieldname": "fixed_price_set_order",
		"fieldtype": "Select",
		"label": "Set Units",
		"options": "\n" + "\n".join(UNIT_ORDERS),
		"insert_after": "fixed_price_set_price",
		"depends_on": "fixed_price_set_qty",
		"description": "Which units make up the sets: the cheapest or the dearest first.",
	},
	{
		"fieldname": "fixed_price_set_repeat",
		"fieldtype": "Check",
		"label": "Repeat Sets",
		"insert_after": "fixed_price_set_order",
		"depends_on": "fixed_price_set_qty",
		"description": "As many sets as the units make up; else one set per document.",
	},
]


def add_discount_limit_fields():
	"""Coupon Code's per-customer limit and eligibility, and Pricing Rule's per-customer limit, shipping
	discount (card 405), eligibility and discount limits (card 407) (install + patches; idempotent)."""
	create_custom_fields(
		{
			"Coupon Code": COUPON_CODE_FIELDS,
			"Pricing Rule": PRICING_RULE_FIELDS
			+ PRICING_RULE_ELIGIBILITY_FIELDS
			+ PRICING_RULE_ALLOTMENT_FIELDS,
		},
		update=True,
	)
