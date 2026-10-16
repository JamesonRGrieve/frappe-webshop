# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (multi-store): coupon codes unique per store (``webshop_store`` on Coupon Code, ERPNext's
unique index on ``coupon_code`` dropped) on existing sites. Idempotent."""

from webshop.webshop.store import scope_coupon_codes_to_stores


def execute():
	scope_coupon_codes_to_stores()
