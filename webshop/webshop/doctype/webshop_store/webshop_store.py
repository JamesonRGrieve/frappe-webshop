# SPDX-License-Identifier: AGPL-3.0-or-later
import frappe
from frappe import _
from frappe.model.document import Document

from webshop.webshop.store import overlay_store


class WebshopStore(Document):
	def validate(self):
		self.validate_unique_company()
		self.validate_pricing()

	def validate_unique_company(self):
		# Orders and payment requests find their store by company, so one store per company.
		other = frappe.db.get_value(
			"Webshop Store", {"company": self.company, "name": ["!=", self.name]}, "name"
		)
		if other:
			frappe.throw(_("Company {0} already sells through store {1}.").format(self.company, other))

	def validate_pricing(self):
		# Reuse Webshop Settings' own checks against this store's company and price list.
		overlay_store(frappe.get_single("Webshop Settings"), self).validate_price_list_exchange_rate()
