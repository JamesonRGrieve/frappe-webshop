import frappe
from erpnext.accounts.doctype.payment_request.payment_request import (
	PaymentRequest as OriginalPaymentRequest,
)
from frappe.utils import get_url

from webshop.webshop.store import get_company_store_settings


class PaymentRequest(OriginalPaymentRequest):
	def on_payment_authorized(self, status=None):
		if not status:
			return

		if status not in ("Authorized", "Completed"):
			return

		if not hasattr(frappe.local, "session"):
			return

		if frappe.local.session.user == "Guest":
			return

		# fork (multi-store): the selling company's store decides where a paid customer lands
		cart_settings = get_company_store_settings(frappe.get_doc("Webshop Settings"), self.company)

		if not cart_settings.enabled:
			return

		success_url = cart_settings.payment_success_url
		redirect_to = get_url("/orders/{0}".format(self.reference_name))

		if success_url:
			redirect_to = (
				{
					"Orders": "/orders",
					"Invoices": "/invoices",
					"My Account": "/me",
				}
			).get(success_url, "/me")

		self.set_as_paid()

		return redirect_to

	@staticmethod
	def get_gateway_details(args):
		if args.order_type != "Shopping Cart":
			return super().get_gateway_details(args)

		# fork (multi-store): each selling company's store has its own gateway account
		cart_settings = get_company_store_settings(frappe.get_doc("Webshop Settings"), args.get("company"))
		gateway_account = cart_settings.payment_gateway_account
		return super().get_payment_gateway_account(gateway_account)
