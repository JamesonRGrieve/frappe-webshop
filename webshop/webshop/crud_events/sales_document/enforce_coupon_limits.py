# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (coupon limits): Quotation, Sales Order and Sales Invoice ``validate`` — the document's coupon code must be
one its customer may use (``webshop.webshop.discounts.coupon_limits``)."""

from webshop.webshop.discounts.coupon_limits import enforce


def execute(doc, method=None):
	enforce(doc)
