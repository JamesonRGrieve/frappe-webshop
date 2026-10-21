# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): Pricing Rule ``validate`` — a per-customer limit needs a coupon-based rule, and a
shipping discount's value fits its kind."""

from webshop.webshop.discounts import coupon_limits, shipping


def execute(doc, method=None):
	coupon_limits.validate_pricing_rule(doc)
	shipping.validate_pricing_rule(doc)
