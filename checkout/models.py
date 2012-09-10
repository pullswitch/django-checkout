import os
import base64
import binascii
from datetime import datetime
from decimal import Decimal

from django.db import models
from django.utils.translation import ugettext_lazy as _

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User

from checkout.settings import CHECKOUT


class OrderManager(models.Manager):

    def incomplete(self):
        return self.filter(status=Order.INCOMPLETE)

    def pending_payment(self):
        return self.filter(status=Order.PENDING_PAYMENT)

    def complete(self):
        return self.filter(status=Order.COMPLETE)

    def voided(self):
        return self.filter(status=Order.VOIDED)

    def refunded(self):
        return self.filter(status=Order.REFUNDED)

    def canceled(self):
        return self.filter(status=Order.CANCELED)


class Order(models.Model):

    INCOMPLETE = "incomplete"
    PENDING_PAYMENT = "pending payment"
    COMPLETE = "complete"
    VOIDED = "voided"
    REFUNDED = "refunded"
    CANCELED = "canceled"

    key = models.CharField(max_length=20, editable=False)

    user = models.ForeignKey(User, null=True, related_name="orders")
    customer_id = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)

    subtotal = models.DecimalField(_("Subtotal"),
        max_digits=18, decimal_places=2, blank=True, null=True)
    tax = models.DecimalField(_("Tax"),
        max_digits=18, decimal_places=2, blank=True, null=True)
    shipping = models.DecimalField(_("Shipping"),
        max_digits=8, decimal_places=2, blank=True, null=True)
    total = models.DecimalField(_("Total"),
        max_digits=18, decimal_places=2, blank=True, null=True)

    discount = models.ForeignKey("Discount", blank=True, null=True)
    discount_amount = models.DecimalField(_("Discount amount"),
        max_digits=18, decimal_places=2, blank=True, null=True)

    creation_date = models.DateTimeField(verbose_name=_('creation date'))

    referral = models.ForeignKey("Referral", blank=True, null=True)

    status = models.CharField(_("Status"), max_length=20, blank=True)

    objects = OrderManager()

    def __unicode__(self):
        return "Order #{0}".format(self.pk)

    @models.permalink
    def get_absolute_url(self):
        return ("checkout_order_details", (self.key, ))

    @property
    def item_count(self):
        return self.items.count()

    def save(self, *args, **kwargs):
        if not self.pk and not self.creation_date:
            self.creation_date = datetime.now()

        if not self.key:
            self.key = self.generate_key()

        super(Order, self).save(*args, **kwargs)

    def generate_key(self, length=8):
        return binascii.b2a_hex(os.urandom(length))

    def successful_transaction(self):
        try:
            return self.transactions.get(status=OrderTransaction.COMPLETE)
        except:
            return None

    @property
    def is_subscription(self):
        for item in self.items.all():
            if item.subscription_plan:
                return True
        return False

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
    subscription_plan = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1, null=True)
    item_price = models.DecimalField(max_digits=18, decimal_places=2)
    item_tax = models.DecimalField(default=Decimal('0.00'), max_digits=18, decimal_places=2)
    total = models.DecimalField(max_digits=18, decimal_places=2)

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

    CREDIT = CHECKOUT["CREDIT"]
    CHECK = CHECKOUT["CHECK"]
    DISCOUNT = CHECKOUT["DISCOUNT"]

    METHOD_CHOICES = CHECKOUT["PAYMENT_METHOD_CHOICES"]

    order = models.ForeignKey(Order, related_name="transactions")

    creation_date = models.DateTimeField()
    status = models.CharField(max_length=20)

    payment_method = models.IntegerField(choices=METHOD_CHOICES, default=1)
    description = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, blank=True, null=True)

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
        ordering = ('-creation_date',)

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
    uses_limit = models.IntegerField(_("Global usage limit"), blank=True, null=True)
    individual_use_limit = models.IntegerField(_("Individual usage limit"), default=1)
    times_used = models.IntegerField(default=0)
    user = models.ForeignKey(User, blank=True, null=True)
    active_date = models.DateTimeField(blank=True, null=True)
    expire_date = models.DateTimeField(blank=True, null=True)

    def __unicode__(self):
        return self.code

    def is_valid(self, user=None):
        if self.active_date and datetime.now() < self.active_date:
            return False
        if self.expire_date and datetime.now() > self.expire_date:
            return False
        if self.uses_limit > 0 and self.times_used >= self.uses_limit:
            return False
        if not self.active:
            return False
        if user:
            if self.user and user != self.user:
                return False
            elif user.orders.filter(discount=self).count() >= self.individual_use_limit:
                # if user has met the usage limit of this discount
                return False
        return True

    def associated_orders(self):
        return self.order_set.all()

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = base64.b16encode(os.urandom(8))

        super(Discount, self).save(*args, **kwargs)

    class Meta:
        ordering = ("active_date", "expire_date", "code")


class Referral(models.Model):
    source = models.CharField(max_length=100)

    def __unicode__(self):
        return u'Referral: %s' % self.source
