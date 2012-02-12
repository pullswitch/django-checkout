import random
from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils.translation import ugettext as _

from django.contrib.auth.models import User

from django_countries.countries import COUNTRIES
from uni_form.helpers import FormHelper, Layout, Fieldset, Row, Submit

from checkout.fields import CreditCardField, ExpiryDateField, VerificationValueField
from checkout.models import Discount
from checkout.utils import import_from_string

BaseSignupForm = import_from_string(getattr(settings,
    "CHECKOUT_BASE_SIGNUP_FORM",
    "django.contrib.auth.forms.UserCreationForm"
))


class CustomItemForm(forms.Form):

    item_description = forms.CharField(max_length=250)
    item_amount = forms.CharField(max_length=5)
    taxable = forms.BooleanField(initial=False, required=False)
    allow_discounts = forms.BooleanField(initial=True, required=False)

    def taxable(self):
        return self.cleaned_data.get("taxable", False)

    def tax(self):
        return Decimal(self.cleaned_data["item_amount"]) * Decimal(getattr(settings, "CHECKOUT_TAX_RATE", .08))

    def total(self):
        return Decimal(self.cleaned_data["item_amount"]) + self.tax()


class PaymentProfileForm(forms.Form):

    card_number = CreditCardField(required=True)
    ccv = VerificationValueField(label="CCV", required=True)
    expiration_date = ExpiryDateField(required=True)

    billing_first_name = forms.CharField(label=_("First name"))
    billing_last_name = forms.CharField(label=_("Last name"))

    address1 = forms.CharField(label=_("Address 1"), max_length=50)
    address2 = forms.CharField(label=_("Address 2"), max_length=50, required=False)
    city = forms.CharField(max_length=40)
    region = forms.CharField(label=_("State/Region"), max_length=75)
    postal_code = forms.CharField(max_length=15)

    country = forms.ChoiceField(choices=COUNTRIES)
    phone_number = forms.CharField(max_length=30)

    discount_code = forms.CharField(max_length=20, required=False)

    helper = FormHelper()

    layout = Layout(
        Fieldset("Payment",
            "card_number",
            Row("ccv", "expiration_date"),
        ),
        Fieldset("Billing Address",
            Row("billing_first_name", "billing_last_name"),
            "address1",
            "address2",
            Row("city", "region", "postal_code"),
            Row("country", "phone_number")
        ),
        Fieldset("",
            "discount_code",
        )
    )
    helper.add_layout(layout)

    def __init__(self, *args, **kwargs):
        super(PaymentProfileForm, self).__init__(*args, **kwargs)
        self.fields["country"].initial = "US"

    def clean_discount_code(self):
        code = self.cleaned_data["discount_code"]

        if code:
            discount = Discount.objects.filter(code__iexact=code)
            if not discount.count() or not discount[0].valid:
                raise forms.ValidationError("This is not a valid discount code")

        return code

    def customize_submit_button(self, id, text):
        button = Submit(id, text)
        self.helper.inputs[0] = button


class CheckoutSignupForm(BaseSignupForm):

    first_name = forms.CharField()
    last_name = forms.CharField()

    def __init__(self, *args, **kwargs):
        super(CheckoutSignupForm, self).__init__(*args, **kwargs)
        del self.fields["username"]
        self.fields.keyOrder = [
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "confirmation_key",
        ]

    def create_user(self, username=None, commit=True):
        email = self.cleaned_data["email"].strip().lower()
        if username is None:
            while True:
                try:
                    username = self.generate_username(email)
                    User.objects.get(username=username)
                except User.DoesNotExist:
                    break
        return super(CheckoutSignupForm, self).create_user(username, commit=commit)

    def generate_username(self, email):
        """
        auth.User requires an unique username so we need to make one up.
        """
        h = sha_constructor(email).hexdigest()[:25]
        # do not ask
        n = random.randint(1, (10 ** (5 - 1)) - 1)
        return "%s%d" % (h, n)

    def after_signup(self, new_user):
        new_user.first_name = self.cleaned_data.get("first_name")
        new_user.last_name = self.cleaned_data.get("last_name")
        new_user.save()
        try:
            profile = new_user.get_profile()
            profile.first_name = new_user.first_name
            profile.last_name = new_user.last_name
            profile.save()
        except:
            pass

    helper = FormHelper()

    layout = Layout(
        Fieldset("Create Your Account",
            "first_name",
            "last_name",
            "email",
            Row("password1", "password2"),
        ),
    )
    helper.add_layout(layout)
    submit = Submit("save-button", "Create and Continue")
    helper.add_input(submit)
