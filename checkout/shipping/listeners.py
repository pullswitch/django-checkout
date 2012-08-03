

def save_shipping_address(sender, order, form, **kwargs):
    from checkout.shipping.models import Address

    address, created = Address.objects.get_or_create(order=order)

    address.address1 = form.cleaned_data["address1"]
    address.address2 = form.cleaned_data["address2"]
    address.city = form.cleaned_data["city"]
    address.region = form.cleaned_data["region"]
    address.country = form.cleaned_data["country"]
    address.postal_code = form.cleaned_data["postal_code"]
    address.save()
