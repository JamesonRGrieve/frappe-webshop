# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (shipping discounts): ERPNext's Shipping Rule, its charge row written less the shipping discount the
document's Pricing Rules give (``webshop.webshop.discounts.shipping``)."""

from erpnext.accounts.doctype.shipping_rule.shipping_rule import ShippingRule

from webshop.webshop.discounts.shipping import discounted_charge


class WebshopShippingRule(ShippingRule):
	def add_shipping_rule_to_tax_table(self, doc, shipping_amount):
		super().add_shipping_rule_to_tax_table(doc, discounted_charge(self, doc, shipping_amount))
