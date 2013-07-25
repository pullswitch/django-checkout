from django.conf.urls import patterns
from django.conf.urls import url


urlpatterns = patterns("checkout.views",
    url(r"^$", "order_list", name="checkout_order_list"),
    url(r"^details/(?P<key>\w+)/$",
    	"order_details",
    	name="checkout_order_details"),
)