# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (rule limits): Quotation, Sales Order and Sales Invoice ``validate`` — the Pricing Rules ERPNext applied go
only to customers they are for, and give no more than their limits (``webshop.webshop.discounts.rule_limits``)."""

from webshop.webshop.discounts.rule_limits import enforce


def execute(doc, method=None):
	enforce(doc)
