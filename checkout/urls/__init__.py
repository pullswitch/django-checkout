from django.conf.urls.defaults import patterns

from checkout.views import CheckoutView, ConfirmView


urlpatterns = patterns("checkout.views",
    (r"^$", CheckoutView.as_view(), {}, "checkout"),
    (r"^confirm/$", ConfirmView.as_view(), {}, "checkout_confirm"),
    (r"^discount/$", "lookup_discount_code", {}, "checkout_lookup_discount"),
)
