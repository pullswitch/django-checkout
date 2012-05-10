import random
from decimal import Decimal

from django import forms
from django.utils.hashcompat import sha_constructor
from django.utils.translation import ugettext as _

from django.contrib.auth.models import User
from django.contrib.auth import login

from django_countries.countries import COUNTRIES
from uni_form.helpers import FormHelper, Layout, Fieldset, Row, Submit

from .fields import CreditCardField, ExpiryDateField, VerificationValueField
from .models import Discount
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


class PaymentProfileForm(forms.Form):

    card_number = CreditCardField(required=True)
    ccv = VerificationValueField(label="CCV", required=True)
    expiration_date = ExpiryDateField(required=True)

    billing_first_name = forms.CharField(label=_("First name"))
    billing_last_name = forms.CharField(label=_("Last name"))

    address1 = forms.CharField(label=_("Address 1"), max_length=50)
    address2 = forms.CharField(label=_("Address 2"), max_length=50, required=False)
    organization = forms.CharField(label=_("Business/Organization"), max_length=50, required=False)
    city = forms.CharField(max_length=40)
    region = forms.CharField(label=_("State/Region"), max_length=75)
    postal_code = forms.CharField(max_length=15)

    country = forms.ChoiceField(choices=COUNTRIES)
    phone_number = forms.CharField(max_length=30)

    discount_code = forms.CharField(max_length=20, required=False)
    referral_source = forms.CharField(label=_("How did you hear about us?"), max_length=100, required=False)
    referral_source_other = forms.CharField(max_length=100, widget=forms.HiddenInput, required=False)

    helper = FormHelper()

    layout = Layout(
        Fieldset("",
            "discount_code",
        ),
        Fieldset("Payment",
            "card_number",
            Row("ccv", "expiration_date"),
        ),
        Fieldset("Billing Address",
            Row("billing_first_name", "billing_last_name"),
            "address1",
            "address2",
            "organization",
            Row("city", "region", "postal_code"),
            Row("country", "phone_number")
        ),
    )
    helper.add_layout(layout)
    submit = Submit("save-button", "Continue")
    helper.add_input(submit)

    def __init__(self, *args, **kwargs):
        if kwargs.get("user"):
            self.user = kwargs.pop("user")
        super(PaymentProfileForm, self).__init__(*args, **kwargs)
        self.fields["country"].initial = "US"
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


class CheckoutSignupForm(BaseSignupForm):

    first_name = forms.CharField()
    last_name = forms.CharField()
    email = forms.CharField()

    def __init__(self, *args, **kwargs):
        super(CheckoutSignupForm, self).__init__(*args, **kwargs)
        del self.fields["username"]
        self.fields.keyOrder = [
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2"
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
        try:
            response = super(CheckoutSignupForm, self).create_user(username, commit=commit)
        except:
            response = User.objects.create_user(username, email=email, password=self.cleaned_data["password1"])
        return response

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

    def login(self, request, user):
        # nasty hack to get get_user to work in Django
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)

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
