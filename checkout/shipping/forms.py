from django import forms
from django.conf import settings
from django.utils.translation import ugettext as _

from form_utils.forms import BetterForm

from checkout.forms import BillingInfoPaymentForm


class ShippingPaymentForm(BillingInfoPaymentForm, BetterForm):

    same_as_billing = forms.BooleanField(
        label=_("Shipping address same as billing?"),
        initial=True,
        required=False
    )
    first_name = forms.CharField(
        label=_("First Name"),
        max_length=40
    )
    last_name = forms.CharField(
        label=_("Last Name"),
        max_length=40
    )
    address1 = forms.CharField(
        label=_("Street Address"),
        max_length=50,
        required=False
    )
    address2 = forms.CharField(
        label=_("Address 2"),
        help_text="Unit, apartment, building number",
        max_length=50,
        required=False
    )
    city = forms.CharField(label=_("City"), max_length=40, required=False)
    region = forms.CharField(label=_("State/Region"), max_length=75, required=False)
    postal_code = forms.CharField(
        label=_("Zip/Postal Code"),
        max_length=15,
        required=False
    )
    phone = forms.CharField(
        label=_("Phone"),
        max_length=20,
        required=False
    )

    if "django_countries" in settings.INSTALLED_APPS:
        from django_countries.countries import COUNTRIES
        country = forms.ChoiceField(choices=COUNTRIES, required=False)
    else:
        country = forms.CharField(
            label=_("Country"),
            max_length=50,
            required=False
        )

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
            }),
            ("", {
                "fields": ["same_as_billing"]
            }),
            ("Shipping Address", {
                "fields": [
                    "first_name",
                    "last_name",
                    "address1",
                    "address2",
                    "city",
                    "region",
                    "postal_code",
                    "country",
                    "phone"
                ],
                "classes": ("shipping",)
            })
        ]

    def clean_first_name(self):
        f = self.cleaned_data["first_name"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_first_name"]
        elif not f:
            raise forms.ValidationError("Ship-to name is required")
        return f

    def clean_last_name(self):
        f = self.cleaned_data["last_name"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_last_name"]
        elif not f:
            raise forms.ValidationError("Ship-to name is required")
        return f

    def clean_address1(self):
        f = self.cleaned_data["address1"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_address1"]
        elif not f:
            raise forms.ValidationError("Street address is required")
        return f

    def clean_address2(self):
        f = self.cleaned_data["address2"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_address2"]
        return f

    def clean_city(self):
        f = self.cleaned_data["city"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_city"]
        elif not f:
            raise forms.ValidationError("City is required")
        return f

    def clean_region(self):
        f = self.cleaned_data["region"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_region"]
        return f

    def clean_postal_code(self):
        f = self.cleaned_data["postal_code"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_postal_code"]
        elif not f:
            raise forms.ValidationError("Postal code is required")
        return f

    def clean_country(self):
        f = self.cleaned_data["country"]
        if self.cleaned_data.get("same_as_billing"):
            return self.cleaned_data["billing_country"]
        return f
