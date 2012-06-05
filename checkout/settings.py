from django.conf import settings

CHECKOUT = {
    "SUBSCRIPTIONS": None,
    "ALLOW_PRERENEWAL": False,
    "ALLOW_PLAN_CREATION": False,
    "PLAN_OPTIONS_GENERATOR": lambda x: {
        "id": "monthly_{0}".format(x),
        "interval": "monthly",
        "amount": x,
        "name": "${0}/Month Plan".format(x)
    },
    "ANONYMOUS_CHECKOUT": False,
    "PRERENEWAL_DISCOUNT_CODE": None,
    "BASE_SIGNUP_FORM": "django.contrib.auth.forms.UserCreationForm",
    "SIGNUP_FORM": "django.contrib.auth.forms.UserCreationForm",
    "REFERRAL_CHOICES": None,
    "TAX_RATE": 0.8,
    "CREDIT": 1,
    "CHECK": 2,
    "DISCOUNT": 3,
    "PAYMENT_FORM": "checkout.forms.PaymentForm",
    "PAYMENT_METHOD_CHOICES": (
        (1, "Credit/Debit"),
        (2, "Check"),
        (3, "Discount/Gift Certificate")
    ),
    "PAYMENT_PROCESSOR": "checkout.processors.braintree_processor"
}

if hasattr(settings, "CHECKOUT"):
    CHECKOUT.update(settings.CHECKOUT)
