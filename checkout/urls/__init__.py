from django.conf.urls.defaults import patterns


urlpatterns = patterns("checkout.views",
    (r"^$", "info", {}, "checkout"),
    (r"^confirm/$", "confirm", {}, "checkout_confirm"),
    (r"^discount/$", "lookup_discount_code", {}, "checkout_lookup_discount"),
)
