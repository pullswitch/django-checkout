from django.conf.urls import patterns
from django.conf.urls import url

from checkout.views import CheckoutView, ConfirmView


urlpatterns = patterns("checkout.views",
    url(r"^$", CheckoutView.as_view(), name="checkout"),
    url(r"^confirm/$", ConfirmView.as_view(), name="checkout_confirm"),
    url(r"^discount/$",
    	"lookup_discount_code",
    	name="checkout_lookup_discount"),
)
