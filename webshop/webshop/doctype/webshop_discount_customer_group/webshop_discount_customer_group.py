# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (rule limits): one customer group a Pricing Rule is for, or never for (``eligible_customer_groups``,
``excluded_customer_groups``)."""

from frappe.model.document import Document


class WebshopDiscountCustomerGroup(Document):
	pass
