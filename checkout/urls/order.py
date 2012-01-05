from django.conf.urls.defaults import patterns, include


urlpatterns = patterns("checkout.views",
    (r"^$", "order_list", {}, "checkout_order_list"),
    (r"^details/(?P<pk>\d+)/$", "order_details", {}, "checkout_order_details"),
)