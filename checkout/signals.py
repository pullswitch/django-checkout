import django.dispatch


pre_handle_billing_info = django.dispatch.Signal(providing_args=["user", "payment_data"])
post_handle_billing_info = django.dispatch.Signal(
    providing_args=["user", "success", "reference_id", "error", "results"]
)

pre_charge = django.dispatch.Signal(providing_args=["order", "transaction"])
post_charge = django.dispatch.Signal(
    providing_args=["order", "transaction", "success", "data"]
)

pre_subscribe = django.dispatch.Signal(providing_args=["order", "transaction"])
post_subscribe = django.dispatch.Signal(
    providing_args=["order", "transaction", "success", "data"]
)

order_complete = django.dispatch.Signal(
    providing_args=["order", ]
)
