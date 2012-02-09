import logging
from decimal import Decimal

from django.conf import settings
from django.utils.translation import ugettext_lazy as _

import braintree

logger = logging.getLogger("checkout.processors.braintree_processor")

# Configure Braintree
braintree.Configuration.configure(
    braintree.Environment.Production if settings.IS_PROD else braintree.Environment.Sandbox,
    settings.BRAINTREE_MERCHANT_ID,
    settings.BRAINTREE_PUBLIC_KEY,
    settings.BRAINTREE_PRIVATE_KEY
)


class Processor:

    def __init__(self, **kwargs):

        if kwargs.get("user", None):
            self.user = kwargs.pop("user")

    def create_customer(self, data):

        # expiration date is date due to different formatting requirements
        formatted_expire_date = data.get("expiration_date").strftime("%m/%Y")

        try:
            result = braintree.Customer.create({
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "company": data["organization"],
                "email": data["email"],
                "phone": data["phone_number"],
                "credit_card": {
                    "number": data.get("card_number"),
                    "expiration_date": formatted_expire_date,
                    "cvv": data["ccv"],
                    "billing_address": {
                        "street_address": data["address1"],
                        "extended_address": data.get("address2"),
                        "postal_code": data["postal_code"],
                        "locality": data["city"],
                        "region": data["region"],
                        "country_code_alpha2": data["country"],
                    }
                }
            })
        except:
            result = {
                "is_success": False,
                "message": _("An exception occurred while creating the customer record")
            }
        return result

    def get_payment_details(self, payment_token):
        try:
            return braintree.CreditCard.find(payment_token)
        except:
            return None

    def get_subscription(self, subscription_id):
        return braintree.Subscription.find(subscription_id)

    def handle_billing_info(self, data, customer_id=None, payment_token=None, **kwargs):

        #default response items
        success = False
        result = None
        error = None

        # expiration date is date due to different formatting requirements
        formatted_expire_date = data.get("expiration_date").strftime("%m/%Y")

        if data.get("customer_id"):
            customer_id = data.get("customer_id")

        if data.get("payment_token"):
            payment_token = data.get("payment_token")

        if customer_id:
            if payment_token:
                # Update customer, credit card & billing address
                # http://www.braintreepayments.com/docs/python/customers/update#update_customer_credit_card_and_billing_address
                result = braintree.Customer.update(customer_id, {
                    "email": data["email"],
                    "phone": data["phone_number"],
                    "credit_card": {
                        "cardholder_name": "%s %s" % (data["billing_first_name"], data["billing_last_name"]),
                        "number": data.get("card_number"),
                        "expiration_date": formatted_expire_date,
                        "cvv": data["ccv"],
                        "options": {
                            "update_existing_token": payment_token,
                        },
                        "billing_address": {
                            "street_address": data["address1"],
                            "postal_code": data["postal_code"],
                            "locality": data["city"],
                            "region": data["region"],
                            "country_code_alpha2": data["country"],
                            "options": {
                                "update_existing": True
                            }
                        }
                    }
                })

            else:
                result = braintree.Customer.update(customer_id, {
                    "email": data["email"],
                    "phone": data["phone_number"],
                    "credit_card": {
                        "cardholder_name": "%s %s" % (data["billing_first_name"], data["billing_last_name"]),
                        "number": data.get("card_number"),
                        "expiration_date": formatted_expire_date,
                        "cvv": data["ccv"],
                        "billing_address": {
                            "street_address": data["address1"],
                            "postal_code": data["postal_code"],
                            "locality": data["city"],
                            "region": data["region"],
                            "country_code_alpha2": data["country"],
                            "options": {
                                "update_existing": True
                            }
                        }
                    }
                })

            """elif billing_profile.payment_token:
                result = braintree.CreditCard.update(billing_profile.payment_token, {
                    "cardholder_name": "%s %s" % (data["billing_first_name"], data["billing_last_name"]),
                    "number": data.get("card_number"),
                    "expiration_date": formatted_expire_date,
                    "cvv": data["ccv"],
                    "billing_address": {
                            "street_address": data["address1"],
                            "postal_code": data["postal_code"],
                            "locality": data["city"],
                            "region": data["region"],
                            "country_code_alpha2": data["country"],
                            "options": {
                                "update_existing": True
                            }
                        }
                })
            """

            if result and not result.is_success:
                # nullify the result to force a normal transaction
                result = None

        if not result:
            # store transaction info in braintree

            result = braintree.Transaction.sale({
                "amount": data.get("amount") or kwargs.get("amount"),
                "credit_card": {
                    "number": data.get("card_number"),
                    "expiration_date": formatted_expire_date,
                    "cvv": data["ccv"],
                },
                "billing": {
                    "first_name": data["billing_first_name"],
                    "last_name": data["billing_last_name"],
                    "street_address": data["address1"],
                    "extended_address": data["address2"],
                    "postal_code": data["postal_code"],
                    "locality": data["city"],
                    "region": data["region"],
                    "country_code_alpha2": data["country"],
                },
                "customer": {
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": data["email"],
                    "phone": data["phone_number"],
                },
                "options": {
                    "submit_for_settlement": False,
                    "store_in_vault": True,
                    "add_billing_address_to_payment_method": True,
                }
            })

        if result:
            success = result.is_success
            if not success:  # this will be from the Transaction class, not Customer
                error = result.message
                logger.warning("Payment profile save failed for {0} {1} ({2})".format(
                    data.get("billing_first_name"), data.get("billing_last_name"), error
                ))
                reference_id = None
            else:
                reference_id = result.transaction.id

        return success, reference_id, error, result

    def submit_for_settlement(self, amount=None, data=None, reference_id=None):

        result = None

        if reference_id:
            result = braintree.Transaction.submit_for_settlement(reference_id)

        elif data:
            formatted_expire_date = data.get("expiration_date").strftime("%m/%Y")
            result = braintree.Transaction.sale({
                "amount": amount or data.get("amount"),
                "credit_card": {
                    "number": data.get("card_number"),
                    "expiration_date": formatted_expire_date,
                    "cvv": data["ccv"],
                },
                "customer": {
                    "email": data["email"],
                },
                "options": {
                    "submit_for_settlement": True
                }
            })

        if result:
            return result.is_success, result

        return False, "No transaction id or data provided"

    def sale(self, amount, customer_id, payment_method_token):
        result = braintree.Transaction.sale({
            "amount": amount,
            "customer_id": customer_id,
            "payment_method_token": payment_method_token
        })
        return result

    def refund(self, reference_id, amount=None):
        transaction = braintree.Transaction.find(reference_id)
        if transaction:
            if amount:
                    transaction = braintree.Transaction.refund(transaction.id, amount)
            else:
                result = braintree.Transaction.refund(transaction.id)

            if not result.is_success:
                errors = result.errors.deep_errors

            return result.is_success or False, errors

        return False, "Transaction could not be found"

    def void(self, reference_id):
        result = braintree.Transaction.void(reference_id)

        if not result.is_success:
            errors = result.errors.deep_errors

        return result.is_success or False, errors

    def extend_subscription(self, subscription_id, amount, discount_code, billing_cycles=1):
        sub = braintree.Subscription.find(subscription_id)
        if not sub.discounts:
            braintree.Subscription.update(subscription_id, {
                "price": amount,
                "discounts": {
                    "add": [
                        {
                            "inherited_from_id": discount_code,
                            "amount": Decimal(amount),
                            "number_of_billing_cycles": 1,
                            "quantity": 1
                        }
                    ]
                }
            })
        else:
            braintree.Subscription.update(subscription_id, {
                "price": amount,
                "discounts": {
                    "update": [
                        {
                            "existing_id": discount_code,
                            "amount": Decimal(amount),
                            "quantity": 2
                        }
                    ]
                }
            })
