# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (multi-store): a coupon code is unique per store instead of site-wide.

ERPNext's unique index on ``coupon_code`` is dropped (``store.scope_coupon_codes_to_stores``), so
this check replaces it: a code may repeat across stores, but not within one. A code with no store
applies in every store, so it clashes with the same code on any store."""

import frappe
from frappe import _

from webshop.webshop.store import coupon_store_filters


def execute(doc, method=None):
	if not doc.coupon_code:
		return

	clash = frappe.get_all(
		"Coupon Code",
		filters={"coupon_code": doc.coupon_code, "name": ["!=", doc.name]},
		or_filters=coupon_store_filters(doc.webshop_store) if doc.webshop_store else None,
		pluck="name",
		limit=1,
	)
	if clash:
		frappe.throw(
			_(
				"Coupon code {0} is already used by {1} in the same store. A code with no Webshop Store applies in every store."
			).format(frappe.bold(doc.coupon_code), frappe.bold(clash[0])),
			frappe.UniqueValidationError,
			title=_("Duplicate Coupon Code"),
		)
