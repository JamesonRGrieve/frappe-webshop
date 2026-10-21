# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): Coupon Code's per-customer limit and eligibility, and Pricing Rule's per-customer limit
and shipping discount, on existing sites. Idempotent."""

from webshop.webshop.discounts.fields import add_discount_limit_fields


def execute():
	add_discount_limit_fields()
