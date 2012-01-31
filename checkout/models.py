from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User

from checkout.fields import CurrencyField


class OrderManager(models.Manager):

    def incomplete(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.INCOMPLETE)

    def pending_payment(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.PENDING_PAYMENT)

    def complete(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.COMPLETE)

    def voided(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.VOIDED)

    def refunded(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.REFUNDED)

    def canceled(self):
        return super(OrderManager, self).get_query_set().filter(status=Order.CANCELED)


class Order(models.Model):

    INCOMPLETE = "incomplete"
    PENDING_PAYMENT = "pending payment"
    COMPLETE = "complete"
    VOIDED = "voided"
    REFUNDED = "refunded"
    CANCELED = "canceled"

    user = models.ForeignKey(User, null=True, related_name="orders")
    notes = models.TextField(_("Notes"), blank=True, null=True)

    subtotal = CurrencyField(_("Subtotal"),
        max_digits=18, decimal_places=10, blank=True, null=True, display_decimal=4)
    tax = CurrencyField(_("Tax"),
        max_digits=18, decimal_places=10, blank=True, null=True)
    total = CurrencyField(_("Total"),
        max_digits=18, decimal_places=10, blank=True, null=True, display_decimal=4)

    discount_code = models.CharField(
        _("Discount Code"), max_length=20, blank=True, null=True,
        help_text=_("Coupon Code"))
    discount = CurrencyField(_("Discount amount"),
        max_digits=18, decimal_places=10, blank=True, null=True)

    creation_date = models.DateTimeField(verbose_name=_('creation date'))

    status = models.CharField(_("Status"), max_length=20, blank=True)

    objects = OrderManager()

    def __unicode__(self):
        if self.user:
            return "Order #{0}: {1}".format(self.id, self.user.get_full_name())

        return "Order#{0}".format(self.id)

    @property
    def item_count(self):
        return self.items.count()

    def save(self, *args, **kwargs):
        if not self.pk:
            self.time_stamp = datetime.now()

        super(Order, self).save(*args, **kwargs)

    def successful_transaction(self):
        try:
            return self.transactions.get(status=OrderTransaction.COMPLETE)
        except:
            return None

    class Meta:
        get_latest_by = "creation_date"
        ordering = ("-creation_date",)


class LineItemManager(models.Manager):
    def get(self, *args, **kwargs):
        if 'product' in kwargs:
            kwargs['content_type'] = ContentType.objects.get_for_model(type(kwargs['product']))
            kwargs['object_id'] = kwargs['product'].pk
            del(kwargs['product'])
        return super(LineItemManager, self).get(*args, **kwargs)


class LineItem(models.Model):
    order = models.ForeignKey(Order, related_name="items")
    content_type = models.ForeignKey(ContentType, null=True)
    object_id = models.PositiveIntegerField(null=True)
    description = models.CharField(max_length=250, blank=True, null=True)
    attributes = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1, null=True)
    item_price = CurrencyField(max_digits=18, decimal_places=10)
    item_tax = CurrencyField(default=Decimal('0.00'), max_digits=18, decimal_places=10)
    total = CurrencyField(max_digits=18, decimal_places=10)

    objects = LineItemManager()

    def __unicode__(self):
        return self.description or self.product.name

    # product
    def get_product(self):
        return self.content_type.get_object_for_this_type(id=self.object_id)

    def set_product(self, product):
        self.content_type = ContentType.objects.get_for_model(type(product))
        self.object_id = product.pk

    product = property(get_product, set_product)


class OrderRevision(models.Model):
    order = models.ForeignKey(Order, related_name="revisions")
    description = models.CharField(max_length=250, blank=True)
    timestamp = models.DateTimeField()

    def __unicode__(self):
        return self.description

    def save(self, **kwargs):
        if not self.timestamp:
            self.timestamp = datetime.now()
        super(OrderRevision, self).save(**kwargs)

    class Meta:
        ordering = ('-timestamp',)
        get_latest_by = 'timestamp'


class OrderTransaction(models.Model):

    INCOMPLETE = "incomplete"
    FAILED = "failed"
    COMPLETE = "complete"
    VOIDED = "voided"
    REFUNDED = "refunded"

    METHOD_CHOICES = getattr(settings, "CHECKOUT_PAYMENT_METHOD_CHOICES", (
        (1, "Credit/Debit"),
        (2, "Check"),
        (3, "Discount/Gift Certificate")
    ))

    order = models.ForeignKey(Order, related_name="transactions")

    creation_date = models.DateTimeField()
    status = models.CharField(max_length=20)

    payment_method = models.IntegerField(choices=METHOD_CHOICES, default=1)
    description = models.CharField(max_length=100, blank=True)
    amount = CurrencyField(max_digits=18, decimal_places=10, blank=True, null=True)

    last_four = models.CharField(max_length=4, blank=True, null=True)
    reference_number = models.CharField(max_length=32, blank=True, null=True)
    details = models.CharField(max_length=250, blank=True, null=True)
    received_data = models.TextField(blank=True, null=True)

    billing_first_name = models.CharField(max_length=50, blank=True)
    billing_last_name = models.CharField(max_length=50, blank=True)
    billing_address1 = models.CharField(max_length=50, blank=True)
    billing_address2 = models.CharField(max_length=50, blank=True)
    billing_city = models.CharField(max_length=50, blank=True)
    billing_region = models.CharField(max_length=50, blank=True)
    billing_postal_code = models.CharField(max_length=30, blank=True)
    billing_country = models.CharField(max_length=2, blank=True)

    class Meta:
        get_latest_by = "creation_date"

    def save(self, **kwargs):
        if not self.pk:
            self.creation_date = datetime.now()

        if not self.status:
            self.status = self.INCOMPLETE

        super(OrderTransaction, self).save(**kwargs)


class Discount(models.Model):

    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=True)
    amount = models.DecimalField(decimal_places=2, max_digits=8, blank=True, null=True)
    percentage = models.IntegerField(blank=True, null=True)
    uses_limit = models.IntegerField(blank=True, null=True)
    times_used = models.IntegerField(default=0)
    user = models.ForeignKey(User, blank=True, null=True)
    active_date = models.DateTimeField(blank=True, null=True)
    expire_date = models.DateTimeField(blank=True, null=True)

    def __unicode__(self):
        return self.code

    def valid(self):
        if self.active_date and datetime.now() < self.active_date:
            return False
        if self.expire_date and datetime.now() > self.expire_date:
            return False
        if self.uses_limit > 0 and self.times_used >= self.uses_limit:
            return False
        if not self.active:
            return False
        return True
    valid = property(valid)

    def associated_orders(self):
        return Order.objects.filter(discount_code=self.code)

    class Meta:
        ordering = ("active_date", "expire_date", "code")


class Referral(models.Model):
    order = models.ForeignKey(Order)
    source = models.CharField(max_length=100)

    def __unicode__(self):
        return u'Referral: %s' % self.source