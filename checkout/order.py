import datetime
import models

ORDER_ID = 'ORDER-ID'


class LineItemAlreadyExists(Exception):
    pass


class LineItemDoesNotExist(Exception):
    pass


class OrderException(Exception):
    pass


class Order:
    def __init__(self, request):
        order_id = request.session.get(ORDER_ID)
        order = None
        if order_id:
            try:
                order = models.Order.objects.get(id=order_id, checked_out=False)
            except models.Order.DoesNotExist:
                pass
        if not order and request.user.is_authenticated():
            if request.user.orders.incomplete().count():
                order = request.user.orders.incomplete().latest()

        if not order:
            order = self.new(request)

        self.order = order
        self.is_subscription = False

    def __iter__(self):
        for item in self.order.items.all():
            yield item

    def get_total(self):
        total = 0
        for item in self:
            total += item.total
        return total

    def new(self, request):
        order = models.Order(
            creation_date=datetime.datetime.now(),
            status=models.Order.INCOMPLETE
        )
        if request.user.is_authenticated():
            order.user = request.user
        order.save()
        request.session[ORDER_ID] = order.id
        # @@ send signal with order id and request for further actions
        return order

    def add(self, item_price, item_tax=0, quantity=1, **kwargs):
        product = kwargs.get("product", None)
        description = kwargs.get("description", "")
        subscription_plan = kwargs.get("subscription_plan", "")
        total = quantity * item_price
        if item_tax:
            total += quantity * item_tax
        try:
            item = models.LineItem.objects.get(
                order=self.order,
                product=product,
                description=description,
                subscription_plan=subscription_plan
            )
        except models.LineItem.DoesNotExist:
            if self.order.items.count() and self.is_subscription:
                raise OrderException
            item = models.LineItem()
            item.order = self.order
            if product:
                item.product = product
            if kwargs.get("attributes"):
                item.attributes = kwargs.get("attributes")
            if subscription_plan:
                item.subscription_plan = subscription_plan
                self.is_subscription = True
            item.item_price = item_price
            item.item_tax = item_tax
            item.total = total
            item.quantity = quantity
            item.description = description
            item.save()
        else:
            raise LineItemAlreadyExists

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
        tax = 0
        total = 0
        for item in self:
            subtotal += item.quantity * item.item_price
            tax += item.quantity * item.item_tax
            total += item.total
        self.order.subtotal = subtotal
        self.order.tax = tax
        if self.order.discount:
            total = float(total) - float(self.order.discount)
        self.order.total = total
        self.order.save()

    def update_status(self, status):
        self.order.status = status
        self.order.save()

        if self.order.status == self.order.COMPLETE and self.order.discount_code:
            discount = models.Discount.objects.get(code=self.order.discount_code)
            if discount.uses_limit:
                discount.times_used += 1
                discount.save()

    def apply_discount(self, code="", amount=None):
        if code:
            discount = models.Discount.objects.get(code=code)
            if discount.valid:
                self.order.discount_code = code
                if discount.amount and discount.amount > 0:
                    self.order.discount = discount.amount
                else:
                    self.order.discount = float(self.get_total()) * (float(discount.percentage) / 100.00)
        elif amount:
            self.order.discount = amount
        self.order.save()
        print self.order.discount

    def clear(self):
        for item in self.order.items.all():
            item.delete()
