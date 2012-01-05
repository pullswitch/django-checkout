import django.dispatch


pre_handle_billing_info = django.dispatch.Signal(providing_args=["user", "payment_data"])
post_handle_billing_info = django.dispatch.Signal(
    providing_args=["user", "success", "reference_id", "error", "results"]
)

pre_submit_for_settlement = django.dispatch.Signal(providing_args=["order", "transaction"])
post_submit_for_settlement = django.dispatch.Signal(
    providing_args=["order", "transaction", "success", "data"]
)
