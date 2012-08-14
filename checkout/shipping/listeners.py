

def save_shipping_address(sender, order, form, **kwargs):
    from checkout.shipping.models import Address

    address, created = Address.objects.get_or_create(order=order)

    address.first_name = form.cleaned_data["first_name"]
    address.last_name = form.cleaned_data["last_name"]
    address.address1 = form.cleaned_data["address1"]
    address.address2 = form.cleaned_data.get("address2")
    address.city = form.cleaned_data["city"]
    address.region = form.cleaned_data.get("region")
    address.country = form.cleaned_data["country"]
    address.postal_code = form.cleaned_data["postal_code"]
    address.phone = form.cleaned_data.get("phone")
    address.save()
