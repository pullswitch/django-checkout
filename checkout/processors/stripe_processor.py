import logging

from django.conf import settings
from django.utils.translation import ugettext_lazy as _

import stripe

logger = logging.getLogger("checkout.processors.stripe_processor")

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET
PRORATE = getattr(settings, "STRIPE_PRORATE", True)


class Processor:

    def __init__(self, **kwargs):

        if kwargs.get("user", None):
            self.user = kwargs.pop("user")

    def create_plan(self, interval, amount, id, name, currency="usd"):
        # convert our amount to CENTS as integer
        amount = int(amount * 100)
        try:
            plan = stripe.Plan.retrieve(id)
        except:
            plan = stripe.Plan.create(
                amount=amount,
                interval=interval,
                name=name,
                currency=currency,
                id=id
            )
        # amount will be in cents so normalize to dollar
        plan["amount"] = plan["amount"] / 100
        return plan

    def create_token(self, number, exp_month, exp_year, cvc, currency=None, **kwargs):
        return stripe.Token.create(
            card={
            "number": number,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "cvc": cvc,
            "address_line1": kwargs.get("address_line1"),
            "address_line2": kwargs.get("address_line2"),
            "address_zip": kwargs.get("address_zip"),
            # "address_city": kwargs.get("address_city"),  # not currently supported
            "address_state": kwargs.get("address_state"),
            "address_country": kwargs.get("address_country")
            }
        )

    def create_customer(self, data, customer_id=None):

        token = data.get("token")
        if not token:

            # expiration date is date due to different formatting requirements
            expire_month = data.get("expiration_date").strftime("%m")
            expire_year = data.get("expiration_date").strftime("%Y")

            token = self.create_token(**{
                "number": data.get("card_number"),
                "exp_month": expire_month,
                "exp_year": expire_year,
                "cvc": data["ccv"],
                "address_line1": data.get("billing_address1"),
                "address_line2": data.get("billing_address2"),
                "address_zip": data.get("billing_postal_code"),
                "address_city": data.get("billing_city"),
                "address_state": data.get("billing_region"),
                "address_country": data.get("billing_country")
            })

        if customer_id:
            try:
                customer = stripe.Customer.retrieve(customer_id)
                customer.card = token
                customer.save()
                return True, customer_id, None, customer
            except:
                pass
        try:
            result = stripe.Customer.create(
                description="Customer for {0}".format(data["email"]),
                email=data["email"],
                card=token
            )
        except:
            return False, None, _("An error occurred while creating the customer record"), None

        return True, result["id"], None, result

    def get_customer(self, customer_id):
        return stripe.Customer.retrieve(customer_id)

    def delete_customer(self, customer_id):
        try:
            cu = stripe.Customer.retrieve(customer_id)
            result = cu.delete()
            return result["deleted"]
        except:
            return False

    def get_customer_card(self, customer_id):
        try:
            customer = self.get_customer(customer_id)
            return customer.active_card
        except:
            return None

    def get_payment_details(self, token):
        try:
            return stripe.Token.retrieve(token)
        except:
            return None

    def get_card_last4(self, card_obj):
        return card_obj.last4

    def get_transaction(self, transaction_id):
        return stripe.Charge.retrieve(transaction_id)

    def charge(self, amount, data=None, customer_id=None, payment_token=None):

        result = None

        # convert our amount to CENTS as integer
        amount = int(amount * 100)

        if customer_id:
            result = stripe.Charge.create(
                amount=amount,
                currency="usd",
                customer=customer_id
            )

        elif payment_token:
            result = stripe.Charge.create(
                amount=amount,
                currency="usd",
                card=payment_token
            )

        elif data:
            expire_month = data.get("expiration_date").strftime("%m")
            expire_year = data.get("expiration_date").strftime("%Y")
            card_data = {
                "name": "{0} {1}".format(data["first_name"], data["last_name"]),
                "number": data.get("card_number"),
                "exp_month": expire_month,
                "exp_year": expire_year,
                "cvc": data["ccv"],
                "address_line1": data["address1"],
                "address_line2": data.get("address2"),
                "address_zip": data["postal_code"],
                "address_state": data["region"],
                "address_country": data["country"],
            }
            result = stripe.Charge.create({
                "amount": amount or data.get("amount"),
                "currency": "usd",
                "card": card_data,
                "description": data["email"],
            })

        if result:
            return result["paid"], result

        return False, "No customer id or data provided"

    def refund(self, reference_id, amount=None):
        try:
            ch = stripe.Charge.retrieve(reference_id)
        except:
            False, "Transaction not found"

        try:
            if amount:
                result = ch.refund(amount=amount)
            else:
                result = ch.refund()
        except:
            "Transaction already refunded"

        return result["refunded"], None

    def void(self, reference_id):
        return self.refund(reference_id)

    def create_subscription(self, customer_id, plan_id, **kwargs):
        try:
            cu = stripe.Customer.retrieve(customer_id)
        except:
            return False, "No matching customer found"
        cu.update_subscription(plan=plan_id, prorate=PRORATE)
        return True, cu

    can_prerenew = False

    def cancel_subscription(self, customer_id):
        try:
            cu = stripe.Customer.retrieve(customer_id)
            result = cu.cancel_subscription()
            return result["status"] == "canceled"
        except:
            return False
