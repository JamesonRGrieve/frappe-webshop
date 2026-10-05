# SPDX-License-Identifier: AGPL-3.0-or-later
import frappe
from frappe.model.document import Document

from webshop.webshop.store import overlay_store


class WebshopStore(Document):
	def validate(self):
		# Several stores may sell as one company: orders record their store, so nothing is
		# looked up by company.
		self.validate_pricing()

	def validate_pricing(self):
		# Reuse Webshop Settings' own checks against this store's company and price list.
		overlay_store(frappe.get_single("Webshop Settings"), self).validate_price_list_exchange_rate()
