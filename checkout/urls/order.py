from django.conf.urls.defaults import patterns


urlpatterns = patterns("checkout.views",
    (r"^$", "order_list", {}, "checkout_order_list"),
    (r"^details/(?P<key>\w+)/$", "order_details", {}, "checkout_order_details"),
)