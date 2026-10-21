# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): what ERPNext's pricing doesn't enforce on a discount, enforced in the cart and in
selling documents — per-customer use limits and eligible customers and emails on Coupon Codes
(``coupon_limits``), and shipping discounts on Pricing Rules (``shipping``). Their fields are customisations of
ERPNext's records (``fields``), added on install and by a patch."""
