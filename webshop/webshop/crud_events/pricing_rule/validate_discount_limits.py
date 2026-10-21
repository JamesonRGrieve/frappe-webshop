# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): Pricing Rule ``validate`` — a per-customer limit needs a coupon-based rule, a shipping
discount's value fits its kind, and its eligibility and discount limits fit the rule (card 407)."""

from webshop.webshop.discounts import coupon_limits, rule_limits, shipping


def execute(doc, method=None):
	coupon_limits.validate_pricing_rule(doc)
	shipping.validate_pricing_rule(doc)
	rule_limits.validate_pricing_rule(doc)
