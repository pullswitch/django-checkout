import datetime
import models

from django.contrib.contenttypes.models import ContentType

from checkout.settings import CHECKOUT

ORDER_ID = CHECKOUT["COOKIE_KEY_ORDER"]


class LineItemAlreadyExists(Exception):
    pass


class LineItemDoesNotExist(Exception):
    pass


class OrderException(Exception):
    pass


class Order:
    def __init__(self, request):
        order_id = request.session.get(ORDER_ID, None)
        order = None
        if order_id:
            try:
                order = models.Order.objects.get(pk=order_id, status__in=(
                    models.Order.INCOMPLETE, models.Order.PENDING_PAYMENT
                ))
            except models.Order.DoesNotExist:
                pass

        if not order or (order.user and (
            request.user.is_authenticated() and order.user != request.user)
        ):
            order = self.new(request)

        self.order = order
        if request.user.is_authenticated() and not self.order.user:
            self.order.user = request.user
            self.order.save()
        request.session[ORDER_ID] = self.order.pk

    def __iter__(self):
        for item in self.order.items.all():
            yield item

    @property
    def pk(self):
        try:
            return self.order.pk
        except:
            None

    @property
    def completed(self):
        return self.get_status() == models.Order.COMPLETE

    @property
    def total(self):
        return self.order.total

    def get_status(self):
        return self.order.status

    def can_complete(self):
        return self.get_status() == models.Order.PENDING_PAYMENT

    def get_transactions(self):
        return self.order.transactions.all()

    def new(self, request):
        order = models.Order(
            creation_date=datetime.datetime.now(),
            status=models.Order.INCOMPLETE
        )
        if request.user.is_authenticated():
            order.user = request.user
        order.save()
        request.session[ORDER_ID] = order.pk
        return order

    def add(self, item_price, item_tax=0, quantity=1, **kwargs):
        product = kwargs.get("product", None)
        description = kwargs.get("description", "")
        subscription_plan = kwargs.get("subscription_plan", "")
        total = quantity * item_price
        if item_tax:
            total += quantity * item_tax
        if product:
            product_content_type = ContentType.objects.get_for_model(product)
            item_search = models.LineItem.objects.filter(
                order=self.order,
                content_type__pk=product_content_type.id,
                object_id=product.pk,
                description=description,
                subscription_plan=subscription_plan
            )
        else:
            item_search = models.LineItem.objects.filter(
                order=self.order,
                description=description,
                subscription_plan=subscription_plan
            )
        if not item_search.count():
            if self.order.items.count() and self.order.is_subscription:
                return
            item = models.LineItem()
            item.order = self.order
            if product:
                item.product = product
            if kwargs.get("attributes"):
                item.attributes = kwargs.get("attributes")
            item.subscription_plan = subscription_plan
            item.item_price = item_price
            item.item_tax = item_tax
            item.total = total
            item.quantity = quantity
            item.description = description
            item.save()
        elif item_search[0].total != total:
            item = item_search[0]
            item.item_price = item_price
            item.item_tax = item_tax
            item.total = total
            item.save()

    def remove(self, product):
        try:
            item = models.LineItem.objects.get(
                order=self.order,
                product=product,
            )
        except models.LineItem.DoesNotExist:
            raise LineItemDoesNotExist
        else:
            item.delete()

    def update(self, product, quantity, unit_price=None):
        try:
            item = models.LineItem.objects.get(
                order=self.order,
                product=product,
            )
            item.quantity = quantity
            item.total = item.quantity * item.item_price
            if item.item_tax:
                item.total += item.quantity * item.item_tax
            item.save()
        except models.LineItem.DoesNotExist:
            raise LineItemDoesNotExist

    def update_totals(self):
        subtotal = 0
        total = 0
        shipping_waiver = False
        tax_waiver = False
        if self.order.discount and self.order.discount.free_shipping:
            shipping_waiver = True
        if self.order.discount and self.order.discount.no_tax:
            tax_waiver = True
        for item in self:
            subtotal += item.quantity * item.item_price
            total += item.total
        self.order.subtotal = subtotal
        if self.order.discount_amount:
            total = subtotal - self.order.discount_amount
            if total < 0:
                total = 0
        if self.order.tax and not tax_waiver:
            total += self.order.tax
        if self.order.shipping and not shipping_waiver:
            total += self.order.shipping
        self.order.subtotal = subtotal
        self.order.total = total
        self.order.save()

    def update_status(self, status):
        self.order.status = status
        self.order.save()

        if self.order.status == self.order.COMPLETE:
            self.complete_order()

    def apply_discount(self, discount=None, amount=None):
        if discount:
            try:
                discount_obj = models.Discount.objects.get(code__iexact=discount)
            except:
                return
            if discount_obj.is_valid(self.order.user):
                self.order.discount = discount_obj
                if discount_obj.amount and discount_obj.amount > 0:
                    self.order.discount_amount = discount_obj.amount
                elif discount_obj.percentage:
                    self.order.discount_amount = float(self.total) * (float(discount_obj.percentage) / 100.00)
                elif discount_obj.no_tax:
                    self.order.discount_amount = self.order.tax
                elif discount_obj.free_shipping:
                    self.order.discount_amount = self.order.shipping
                transaction, created = models.OrderTransaction.objects.get_or_create(
                    order=self.order,
                    payment_method=models.OrderTransaction.DISCOUNT
                )
                if (transaction.amount != self.order.discount_amount or
                    transaction.reference_number != discount_obj.code):
                    transaction.amount = self.order.discount_amount
                    transaction.reference_number = discount_obj.code
                    transaction.save()
        elif amount:
            self.order.discount_amount = amount
        self.order.save()
        self.update_totals()

    def add_referral(self, referral_text):
        referral, created = models.Referral.objects.get_or_create(
            source=referral_text
        )
        self.order.referral = referral
        self.order.save()

    def complete_order(self):
        self.order.status = models.Order.COMPLETE
        self.order.save()
        if self.order.discount:
            self.order.discount.times_used += 1
            if self.order.discount.user or not self.order.discount.is_valid():
                self.order.discount.active = False
            self.order.discount.save()

    def clear(self):
        self.order.items.all().delete()
        self.order.transactions.all().delete()
        self.order.discount = None
        self.order.discount_amount = 0
        self.order.status = models.Order.INCOMPLETE
        self.order.save()
