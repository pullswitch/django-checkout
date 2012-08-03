from django.db import models
from django.utils.translation import ugettext_lazy as _

from checkout.shipping.listeners import save_shipping_address
from checkout.models import Order
from checkout.signals import form_complete


class Address(models.Model):
    """
    Shipping address information associated with an order
    """
    order = models.OneToOneField(Order)
    address1 = models.CharField(_("Street Address"), max_length=80)
    address2 = models.CharField(_("Street Address 2"), max_length=80, blank=True)
    city = models.CharField(_("City"), max_length=50)
    region = models.CharField(_("State/Region"), max_length=50, blank=True)
    postal_code = models.CharField(_("Postal Code"), max_length=30)
    country = models.CharField(max_length=2, blank=True)

    def __unicode__(self):
        return u"Ship Address for {0}".format(self.order)

    class Meta:
        verbose_name = _("Shipping Address")
        verbose_name_plural = _("Shipping Addresses")


form_complete.connect(save_shipping_address)
