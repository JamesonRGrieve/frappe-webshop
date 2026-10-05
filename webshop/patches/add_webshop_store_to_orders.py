# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (multi-store): add the ``webshop_store`` link to Quotation and Sales Order on existing sites."""

from webshop.webshop.store import add_order_store_fields


def execute():
	add_order_store_fields()
