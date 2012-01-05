from django.conf.urls.defaults import patterns, include


urlpatterns = patterns("checkout.views",
    (r"^$", "info", {}, "checkout"),
    (r"^confirm/$", "confirm", {}, "checkout_confirm"),
)