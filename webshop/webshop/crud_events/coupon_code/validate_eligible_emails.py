# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (coupon limits): Coupon Code ``validate`` — its eligible emails are addresses or ``*`` patterns."""

from webshop.webshop.discounts.coupon_limits import validate_coupon_code


def execute(doc, method=None):
	validate_coupon_code(doc)
