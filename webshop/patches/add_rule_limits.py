# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (rule limits): Pricing Rule's eligibility (customers, customer groups, order history) and discount limits
(cap, spread amount, discounted quantity, fixed-price sets) on existing sites. Idempotent."""

from webshop.webshop.discounts.fields import add_discount_limit_fields


def execute():
	add_discount_limit_fields()
