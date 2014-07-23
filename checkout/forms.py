import re
from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils.translation import ugettext as _

from form_utils.forms import BetterForm

from .fields import CreditCardField, ExpiryDateField, VerificationValueField
from .settings import CHECKOUT
from .utils import import_from_string


BaseSignupForm = import_from_string(CHECKOUT["BASE_SIGNUP_FORM"])


class CustomItemForm(forms.Form):

    item_description = forms.CharField(max_length=250)
    item_amount = forms.CharField(max_length=5)
    taxable = forms.BooleanField(initial=False, required=False)
    allow_discounts = forms.BooleanField(initial=True, required=False)

    def taxable(self):
        return self.cleaned_data.get("taxable", False)

    def tax(self):
        return Decimal(self.cleaned_data["item_amount"]) * Decimal(CHECKOUT["TAX_RATE"])

    def total(self):
        return Decimal(self.cleaned_data["item_amount"]) + self.tax()


class SubscriptionForm(forms.Form):

    if CHECKOUT["SUBSCRIPTIONS"]:
        subscription = forms.ChoiceField(choices=(
                (CHECKOUT["SUBSCRIPTIONS"][s]["id"],
                CHECKOUT["SUBSCRIPTIONS"][s]["name"])
                for s in CHECKOUT["SUBSCRIPTIONS"].keys()
            )
        )
    else:
        subscription = forms.CharField(max_length=100)


class SimplePaymentForm(forms.Form):

    """
    This may not be an option depending on your payment processor
    Both Stripe and Braintree can create a transaction with
    only the credit card details

    It will adapt to use a Stripe-provided token if present
    """
    amount = forms.DecimalField(widget=forms.HiddenInput)
    email = forms.EmailField(max_length=100, required=True)
    card_number = CreditCardField(required=True)
    ccv = VerificationValueField(label="CCV", required=True)
    expiration_date = ExpiryDateField(required=True)
    token = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.HiddenInput
    )

    def __init__(self, *args, **kwargs):
        super(SimplePaymentForm, self).__init__(*args, **kwargs)
        if self.data and self.data.get("token"):
            self.fields["card_number"].required = False
            self.fields["ccv"].required = False
            self.fields["expiration_date"].required = False


class BillingInfoPaymentForm(BetterForm, SimplePaymentForm):

    billing_first_name = forms.CharField(label=_("First name"))
    billing_last_name = forms.CharField(label=_("Last name"))

    billing_address1 = forms.CharField(label=_("Address 1"), max_length=50)
    billing_address2 = forms.CharField(label=_("Address 2"), max_length=50, required=False)
    organization = forms.CharField(label=_("Business/Organization"), max_length=50, required=False)
    billing_city = forms.CharField(label=_("City"), max_length=40)
    billing_region = forms.CharField(label=_("State/Region"), max_length=75)
    billing_postal_code = forms.CharField(label=_("Zip/Postal Code"), max_length=15)

    if "django_countries" in settings.INSTALLED_APPS:
        from django_countries import countries import
        billing_country = forms.ChoiceField(choices=countries)
    else:
        billing_country = forms.CharField(label=_("Country"), max_length=50)

    class Meta:
        fieldsets = [
            ("Credit Card", {
                "fields": ["card_number", "ccv", "expiration_date"]
            }),
            ("Billing Address", {
                "fields": [
                    "email",
                    "billing_first_name",
                    "billing_last_name",
                    "billing_address1",
                    "billing_address2",
                    "organization",
                    "billing_city",
                    "billing_region",
                    "billing_postal_code",
                    "billing_country",
                ]
            })
        ]

    def __init__(self, *args, **kwargs):
        if kwargs.get("user"):
            self.user = kwargs.pop("user")
        super(BillingInfoPaymentForm, self).__init__(*args, **kwargs)
        self.fields["billing_country"].initial = "US"


class SubscriptionPaymentForm(SubscriptionForm, SimplePaymentForm):

    pass


class PaymentForm(BillingInfoPaymentForm):

    discount_code = forms.CharField(max_length=20, required=False)
    referral_source = forms.CharField(label=_("How did you hear about us?"), max_length=100, required=False)
    referral_source_other = forms.CharField(max_length=100, widget=forms.HiddenInput, required=False)

    class Meta:
        fieldsets = [
            ("main", {
                "fields": ["discount_code"]
            }),
            ("Payment", {
                "fields": ["card_number", "ccv", "expiration_date"]
            }),
            ("Billing Address", {
                "fields": [
                    "email",
                    "billing_first_name",
                    "billing_last_name",
                    "billing_address1",
                    "billing_address2",
                    "organization",
                    "billing_city",
                    "billing_region",
                    "billing_postal_code",
                    "billing_country",
                ]
            })
        ]

    def __init__(self, *args, **kwargs):
        if kwargs.get("user"):
            self.user = kwargs.pop("user")
        super(PaymentForm, self).__init__(*args, **kwargs)
        if CHECKOUT["REFERRAL_CHOICES"]:
            self.fields["referral_source"] = forms.MultipleChoiceField(
                label=self.fields["referral_source"].label,
                widget=forms.CheckboxSelectMultiple,
                choices=CHECKOUT["REFERRAL_CHOICES"],
                required=False
            )

    def clean_discount_code(self):
        code = self.cleaned_data["discount_code"]

        if code:
            from checkout.models import Discount

            if Discount.objects.filter(code__iexact=code):
                discount = Discount.objects.get(code__iexact=code)
                try:
                    valid = discount.is_valid(self.user)
                except:
                    valid = discount.is_valid()
                if not valid:
                    raise forms.ValidationError("This is not a valid redemption code")
            else:
                raise forms.ValidationError("This is not a valid redemption code")
        return code


alnum_re = re.compile(r"^\w+$")


class PaymentSignupForm(PaymentForm):

    username = forms.CharField(
        label=_("Username"),
        max_length=30,
        widget=forms.TextInput(),
        required=True
    )
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(render_value=False)
    )
    password_confirm = forms.CharField(
        label=_("Password (again)"),
        widget=forms.PasswordInput(render_value=False)
    )
    email = forms.EmailField(widget=forms.TextInput(), required=True)

    def clean_username(self):
        if not alnum_re.search(self.cleaned_data["username"]):
            raise forms.ValidationError(_("Usernames can only contain letters, numbers and underscores."))
        return self.cleaned_data["username"]

    def clean(self):
        if "password" in self.cleaned_data and "password_confirm" in self.cleaned_data:
            if self.cleaned_data["password"] != self.cleaned_data["password_confirm"]:
                raise forms.ValidationError(_("You must type the same password each time."))
        return self.cleaned_data
