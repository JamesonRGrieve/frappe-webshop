# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fork (discount limits): what ERPNext's pricing doesn't enforce on a discount, enforced in the cart and in
selling documents — per-customer use limits and eligible customers and emails on Coupon Codes
(``coupon_limits``), shipping discounts on Pricing Rules (``shipping``), and Pricing Rules' eligibility
(segments of customers and customer groups, excluded groups, order history) and discount limits (a cap, an amount
spread across lines, a discounted quantity, fixed-price sets) (``rule_limits``), on the rules ERPNext's pricing
applies (``applied``). Their fields are customisations of
ERPNext's records (``fields``), added on install and by a patch."""
