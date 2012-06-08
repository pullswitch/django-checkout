import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render_to_response
from django.template import RequestContext
from django.utils.importlib import import_module
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from django.contrib import messages, auth
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from .models import Discount, Order as OrderModel, OrderTransaction
from .order import Order, ORDER_ID
from .forms import CustomItemForm, SubscriptionForm
from .settings import CHECKOUT
from checkout import signals
from .utils import import_from_string


payment_module = import_module(CHECKOUT["PAYMENT_PROCESSOR"])
PaymentForm = import_from_string(CHECKOUT["PAYMENT_FORM"])
SignupForm = import_from_string(CHECKOUT["SIGNUP_FORM"])


class CheckoutView(FormView):

    """
    Checkout for a single item (no cart)
    """

    template_name = "checkout/form.html"
    template_name_ajax = "checkout/form.html"
    empty_redirect = "home"
    form_class = PaymentForm
    form_class_signup = SignupForm
    processor = payment_module.Processor()
    method = "direct"
    messages = {
        "customer_info_error": {
            "level": messages.WARNING,
            "text": _("The billing info could not be verified")
        }
    }

    def get(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)
        return super(CheckoutView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        incoming = self.retrieve_item()
        if incoming:
            response_kwargs = {
                "request": self.request,
                "template": self.template_name,
                "context": {
                    "form": self.get_form(self.get_form_class()),
                    "order": self.order_obj.order,
                }
            }
            return self.response_class(**response_kwargs)
        elif not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)
        if not self.request.user.is_authenticated() and not CHECKOUT["ANONYMOUS_CHECKOUT"]:
            signup = self.form_class_signup(self.request.POST)
            if signup.is_valid():
                user = self.create_user(signup)
                auth.login(self.request, user)

        return super(CheckoutView, self).post(*args, **kwargs)

    def retrieve_item(self):
        cf = CustomItemForm(self.request.POST)
        if cf.is_valid():
            self.order_obj.add(
                cf.cleaned_data.get("item_amount"),
                description=cf.cleaned_data.get("item_description")
            )
            self.order_obj.update_totals()
            return True
        return False

    def get_initial(self):
        initial = super(CheckoutView, self).get_initial()
        initial["amount"] = self.order_obj.total
        if self.order_obj.get_transactions().count():
            billing_data = self.order_obj.get_transactions().latest()
            initial.update(billing_data)
        return initial

    def get_context_data(self, **kwargs):
        ctx = kwargs
        if self.order_obj.order.discount:
            ctx["discount"] = self.order_obj.order.discount_amount
        ctx.update({
            "checkout_method": self.method,
            "order": self.order_obj.order,
        })
        return ctx

    def form_valid(self, form):
        if self.request.POST.get("referral_source"):
            referral = ", ".join(self.request.POST["referral_source"])
            if referral == "Other" and self.request.POST.get("referral_source_other"):
                referral = self.request.POST["referral_source_other"]
            self.order_obj.add_referral(referral)
        success = self.save_customer_info(form)
        if success:
            return redirect(self.get_success_url())
        else:
            messages.add_message(
                self.request,
                self.messages["customer_info_error"]["level"],
                self.messages["customer_info_error"]["text"]
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        if self.order_obj.total == 0:
            return redirect(self.get_success_url())

        signals.checkout_attempt.send(
            sender=self.form_class,
            order=self.order_obj.order,
            result=form.is_valid()
        )
        return super(CheckoutView, self).form_invalid(form)

    def create_user(self, form, commit=True, **kwargs):
        user = User(**kwargs)
        username = form.cleaned_data.get("username")
        if username is None:
            username = self.generate_username(form)
        user.username = username
        user.email = form.cleaned_data["email"].strip()
        password = form.cleaned_data.get("password")
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        if commit:
            user.save()
        return user

    def save_customer_info(self, form):
        payment_data = form.cleaned_data
        if self.request.user.is_authenticated():
            payment_data.update({
                "email": self.request.user.email,
                "first_name": self.request.user.first_name,
                "last_name": self.request.user.last_name,
            })

        success, reference_id, error, results = self.processor.create_customer(
            payment_data
        )

        signals.post_create_customer.send(
            sender=None,
            user=self.request.user,
            success=success,
            reference_id=reference_id,
            error=error,
            results=results
        )

        if success:
            card_details = self.processor.get_customer_card(reference_id)

            OrderTransaction.objects.get_or_create(
                order=self.order_obj.order,
                amount=self.order_obj.order.total,
                payment_method=OrderTransaction.CREDIT,
                last_four=self.processor.get_card_last4(card_details),
                reference_number=reference_id,
                billing_first_name=form.cleaned_data.get("billing_first_name"),
                billing_last_name=form.cleaned_data.get("billing_last_name"),
                billing_address1=form.cleaned_data.get("address1"),
                billing_address2=form.cleaned_data.get("address2"),
                billing_city=form.cleaned_data.get("city"),
                billing_region=form.cleaned_data.get("region"),
                billing_postal_code=form.cleaned_data.get("postal_code"),
                billing_country=form.cleaned_data.get("country"),
            )

            self.order_obj.update_totals()
            self.order_obj.update_status(OrderModel.PENDING_PAYMENT)
            return True
        return False


class SubscribeView(CheckoutView):

    method = "subscription"

    def retrieve_item(self):
        sf = SubscriptionForm(self.request.POST)
        if sf.is_valid():
            plan = getattr(
                CHECKOUT["SUBSCRIPTIONS"],
                self.request.POST.get("subscription"),
                None
            )
            if not plan and CHECKOUT["ALLOW_PLAN_CREATION"]:
                plan_opts = CHECKOUT["PLAN_OPTIONS_GENERATOR"](
                    self.request.POST.get("amount")
                )
                plan = self.processor.create_plan(**plan_opts)
            if plan:
                self.order_obj.add(
                    plan["rate"],
                    description=plan["description"],
                    subscription_plan=plan["plan_id"]
                )
                self.order_obj.update_totals()
                return True
        return False


class CartView(CheckoutView):

    method = "cart"

    def get(self, *args, **kwargs):
        from cart.cart import CART_ID
        from cart.models import Cart as CartModel

        self.order_obj = Order(self.request)
        cart = CartModel.objects.get(pk=self.request.session[CART_ID])
        for item in cart.item_set.all():
            try:
                self.order_obj.add(
                    item.unit_price,
                    product=item.product,
                    attributes=item.attributesitem
                )
            except:
                self.order_obj.add(
                    item["amount"],
                    attributes=item.get("attributes", ""),
                    description=item["description"]
                )

        self.order_obj.update_totals()
        if not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)
        return super(CartView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if self.request.POST.get("discount_code"):
            self.order_obj.apply_discount(self.request.POST.get("discount_code"))
        if not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)
        if not self.request.user.is_authenticated() and not CHECKOUT["ANONYMOUS_CHECKOUT"]:
            signup = self.form_class_signup(self.request.POST)
            if signup.is_valid():
                user = self.create_user(signup)
                auth.login(self.request, user)

        return super(CartView, self).post(*args, **kwargs)

    def retrieve_item(self):
        # items aren't added via post to this view
        return False


"""def info(request,
    payment_form_class=PaymentForm,
    signup_form_class=SignupForm,
    empty_cart_url="cart", **kwargs):

    template_name = kwargs.get("template_name", "checkout/form.html")

    checkout_summary = {
        "method": "cart" if "cart" in settings.INSTALLED_APPS else "direct",
        "items": [],
        "discount": 0,
        "tax": 0,
        "total": 0
    }

    billing_data = None
    order = None
    signup_form = None

    if request.user.is_authenticated():
        order = Order(request)

    # be helpful and look for stored billing data to autopop with
    if order and order.get_transactions().count():
        billing_data = order.get_transactions().latest()

    if order and order.order.discount:
        checkout_summary["discount"] = order.order.discount_amount

    if request.method == "POST":

        pp = payment_module.Processor()

        if  (request.POST.get("item_description") or
            request.POST.get("custom_confirm")
        ):
            checkout_summary["method"] = "custom"
            custom_form = CustomItemForm(request.POST)
            if custom_form.is_valid():
                checkout_summary["items"].append({
                    "description": custom_form.cleaned_data["item_description"],
                    "amount": custom_form.cleaned_data["item_amount"],
                    "attributes": custom_form.cleaned_data["item_attributes"]
                })
                checkout_summary["tax"] = custom_form.tax()
                checkout_summary["total"] = custom_form.total()
        elif request.POST.get("subscription") and CHECKOUT["SUBSCRIPTIONS"]:
            plan = getattr(CHECKOUT["SUBSCRIPTIONS"], request.POST.get("subscription"), None)
            checkout_summary["method"] = "subscription"
            if plan:
                checkout_summary["items"].append({
                    "description": plan["description"],
                    "amount": plan["rate"],
                    "subscription_plan": plan["plan_id"]
                })
            elif CHECKOUT["ALLOW_PLAN_CREATION"]:
                plan_opts = CHECKOUT["PLAN_OPTIONS_GENERATOR"](
                    request.POST.get("amount")
                )
                plan = pp.create_plan(**plan_opts)
                checkout_summary["items"].append({
                    "description": plan["description"],
                    "amount": plan["rate"],
                    "subscription_plan": plan["plan_id"]
                })
            checkout_summary["total"] = plan["rate"]

    if checkout_summary["method"] == "cart":
        # Look for cart in session
        # The cart remains active until order is completed
        try:
            cart = CartModel.objects.get(pk=request.session[CART_ID])
            checkout_summary["items"] = cart.item_set.all()
            checkout_summary["total"] = cart.total
        except:
            cart = None

        # No cart and no order == cya
        if not order and (not cart or not cart.item_set.count()):
            return redirect(empty_cart_url)

    if not request.user.is_authenticated():
        # @@ to do: if combo_form_class == None, use login_required approach
        SignupForm = signup_form_class
    else:
        SignupForm = None
    Form = payment_form_class

    if request.method == "POST" and (
        checkout_summary["method"] == "cart" or
        request.POST.get("custom_confirm") or
        request.POST.get("subscription_confirm")
    ):
        if SignupForm and not CHECKOUT["ANONYMOUS_CHECKOUT"]:
            signup_form = SignupForm(request.POST)
            if signup_form.is_valid() and not request.user.is_authenticated():
                # @@ user creation needs a new approach
                try:
                    user = signup_form.save()
                except:
                    user = signup_form.create_user()
                try:
                    signup_form.login(request, user)
                except:
                    from django.contrib import auth
                    user.backend = "django.contrib.auth.backends.ModelBackend"
                    auth.login(request, user)
                    request.session.set_expiry(0)

        form = Form(request.POST)
        if request.user.is_authenticated():

            # create order instance
            if not order:
                order = Order(request)
            request.session[ORDER_ID] = order.pk
            success = False  # default success flag

            for item in checkout_summary["items"]:
                try:
                    order.add(
                        item.unit_price,
                        product=item.product,
                        attributes=item.attributes
                    )
                except AttributeError:
                    order.add(
                        item["amount"],
                        attributes=item.get("attributes", ""),
                        description=item["description"],
                        subscription_plan=item.get("subscription_plan", "")
                    )

            if request.POST.get("discount_code"):
                order.apply_discount(request.POST.get("discount_code"))
                if order.order.discount_amount:
                    checkout_summary["discount"] = order.order.discount_amount
                    checkout_summary["total"] -= order.order.discount_amount
                    OrderTransaction.objects.get_or_create(
                        order=order.order,
                        amount=order.order.discount_amount,
                        payment_method=OrderTransaction.DISCOUNT,
                        reference_number=order.order.discount.code
                    )

            order.update_totals()

            if form.is_valid() or order.order.total == 0:
                # clean up any old incomplete orders
                for abandoned in OrderModel.objects.filter(
                        user=request.user
                    ).exclude(pk=order.order.pk).filter(
                        Q(status=OrderModel.PENDING_PAYMENT) | Q(status=OrderModel.INCOMPLETE)
                    ):
                    abandoned.items.all().delete()
                    abandoned.delete()

                # handle referral source -- use POST in case form is not valid (discount)
                if request.POST.get("referral_source"):
                    referral = ", ".join(request.POST["referral_source"])
                    if referral == "Other" and request.POST.get("referral_source_other"):
                        referral = request.POST["referral_source_other"]
                    referral, created = Referral.objects.get_or_create(
                        source=referral
                    )
                    order.order.referral = referral
                    order.order.save()

                if order.order.total > 0 and form.is_valid():

                    payment_data = form.cleaned_data
                    if request.user.is_authenticated():
                        payment_data.update({
                            "email": request.user.email,
                            "first_name": request.user.first_name,
                            "last_name": request.user.last_name,
                        })

                    success, reference_id, error, results = pp.create_customer(
                        payment_data
                    )

                    post_handle_billing_info.send(
                        sender=None,
                        user=request.user,
                        success=success,
                        reference_id=reference_id,
                        error=error,
                        results=results
                    )

                    if success:

                        card_details = pp.get_customer_card(reference_id)

                        OrderTransaction.objects.get_or_create(
                            order=order.order,
                            amount=order.order.total,
                            payment_method=OrderTransaction.CREDIT,
                            last_four=pp.get_card_last4(card_details),
                            reference_number=reference_id,
                            billing_first_name=form.cleaned_data.get("billing_first_name"),
                            billing_last_name=form.cleaned_data.get("billing_last_name"),
                            billing_address1=form.cleaned_data.get("address1"),
                            billing_address2=form.cleaned_data.get("address2"),
                            billing_city=form.cleaned_data.get("city"),
                            billing_region=form.cleaned_data.get("region"),
                            billing_postal_code=form.cleaned_data.get("postal_code"),
                            billing_country=form.cleaned_data.get("country"),
                        )

                        order.update_totals()
                        order.update_status(OrderModel.PENDING_PAYMENT)

                    else:
                        form._errors.update({"__all__": [error, ]})

                elif order.order.total == 0:
                    success = True

                if success:
                    return redirect("checkout_confirm")
    else:
        form = Form()
        if request.user.is_authenticated():
            signup_form = None
            if billing_data:
                for field in form.fields:
                    if hasattr(billing_data, field):
                        form.fields[field].initial = getattr(billing_data, field)
            else:
                if "billing_first_name" in form.fields:
                    form.fields["billing_first_name"].initial = request.user.first_name
                if "billing_last_name" in form.fields:
                    form.fields["billing_last_name"].initial = request.user.last_name
        elif SignupForm:
                signup_form = SignupForm()

    return render_to_response(template_name, {
        "form": form,
        "signup_form": signup_form,
        "checkout_summary": checkout_summary,
        "order": order
    }, context_instance=RequestContext(request))"""


class ConfirmView(TemplateView):

    template_name = "checkout/confirm.html"
    template_name_ajax = "checkout/confirm.html"
    processor = payment_module.Processor()
    messages = {
        "invalid_order": {
            "level": messages.WARNING,
            "text": _("Please try your order again")
        },
        "processing_failed": {
            "level": messages.WARNING,
            "text": _("We were unable to process your card for the following reason: {0}")
        }
    }

    def get(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if not self.order_obj.can_complete():
            return self.invalid_order()
        try:
            self.transaction = self.order_obj.get_transactions().latest()
        except:
            # this may not be acceptable
            self.transaction = None

        return super(ConfirmView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if not self.order_obj.can_complete():
            return self.invalid_order()

        if self.order_obj.total == 0:
            success = True
        elif self.order_obj.order.is_subscription:
            item = self.order_obj.order.items.all()[0]
            success, data = self.processor.create_subscription(
                customer_id=self.transaction.reference_number,
                plan_id=item.subscription_plan,
                price=self.transaction.amount
            )
        else:
            success, data = self.processor.charge(
                self.order_obj.total,
                customer_id=self.transaction.reference_number
            )

        if not success:
            self.transaction.status = self.transaction.FAILED
            self.transaction.received_data = str(data)
            self.transaction.save()
            signals.confirm_attempt.send(
                sender=None,
                order=self.order_obj.order,
                transaction=self.transaction
            )
            messages.add_message(
                self.request,
                self.messages["processing_failed"]["level"],
                self.messages["processing_failed"]["text"].format(data)
            )
        else:
            self.transaction.status = self.transaction.SUCCESS
            self.transaction.save()
            if self.order_obj.order.is_subscription:
                signals.subscribe.send(
                    sender=ConfirmView,
                    order=self.order_obj.order,
                    transaction=self.transaction,
                    request=self.request
                )
            else:
                signals.charge.send(
                    sender=ConfirmView,
                    order=self.order_obj.order,
                    transaction=self.transaction,
                    request=self.request
                )

            self.order_obj.update_status(OrderModel.COMPLETE)
            signals.order_complete.send(
                sender=ConfirmView,
                order=self.order_obj.order
            )
            if ORDER_ID in self.request.session:
                del self.request.session[ORDER_ID]

            self.after_order()

        return super(ConfirmView, self).post(*args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = kwargs
        ctx.update({
            "transaction": self.transaction,
            "order": self.order_obj.order,
        })
        return ctx

    def after_order(self):
        pass

    def invalid_order(self):
        if self.order_obj.completed:
            return redirect("checkout_order_details", self.order_obj.pk)
        if ORDER_ID in self.request.session:
            del self.request.session[ORDER_ID]
        messages.add_message(
            self.request,
            self.messages["invalid_order"]["level"],
            self.messages["invalid_order"]["text"]
        )
        return redirect("checkout")


class CartConfirmView(ConfirmView):

    def after_order(self):
        from cart.cart import CART_ID
        from cart.models import Cart as CartModel
        try:
            cart = CartModel.objects.get(pk=self.request.session[CART_ID])
            cart.item_set.all().delete()
            cart.delete()
        except:
            pass


"""
def confirm(request, **kwargs):

    template_name = kwargs.pop("template_name", "checkout/confirm.html")
    ajax_template_name = kwargs.pop("template_name", template_name)

    try:
        order = Order(request)
        if order.get_transactions().count():
            transaction = order.get_transactions().latest()
        else:
            transaction = None
    except:
        return redirect("checkout")

    if order.order.status not in (OrderModel.INCOMPLETE, OrderModel.PENDING_PAYMENT):
        if ORDER_ID in request.session:
            del request.session[ORDER_ID]
        if order.order.status == OrderModel.COMPLETE:
            return redirect("checkout_order_details", order.pk)
        messages.add_message(request, messages.WARNING, _("Please try your order again"))
        redirect("checkout")

    if request.method == "POST" or order.order.total == 0:

        if order.order.total == 0:
            success = True
            if order.order.is_subscription:
                signals.pre_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction
                )
                signals.post_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction,
                    request=request
                )
        else:
            pp = payment_module.Processor()

            if order.order.is_subscription:

                # look for existing subs
                # @@ problem: stripe makes it easy to check
                # a customer for sub; braintree seemingly does not;
                # instead they want you to search by a customer-specific
                # subscription id. not compatible with stripe's approach

                signals.pre_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction
                )
                item = order.order.items.all()[0]
                success, data = pp.create_subscription(
                    customer_id=transaction.reference_number,
                    plan_id=item.subscription_plan,
                    price=transaction.amount
                )
                if success:
                    transaction.status = transaction.COMPLETE
                else:
                    transaction.status = transaction.FAILED

                signals.post_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction,
                    data=data,
                    request=request
                )
            else:
                signals.pre_charge.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction
                )

                success, data = pp.charge(order.order.total, customer_id=transaction.reference_number)

                # NOTE: if trans failed, data == error code + verbose error message
                transaction.received_data = str(data)
                if success:
                    transaction.status = transaction.COMPLETE
                else:
                    transaction.status = transaction.FAILED
                transaction.save()

                signals.post_charge.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction,
                    success=success,
                    data=data
                )

        if success:
            order.update_status(OrderModel.COMPLETE)
            signals.order_complete.send(sender=CheckoutView, order=order.order)
            if ORDER_ID in request.session:
                del request.session[ORDER_ID]
            try:
                cart = CartModel.objects.get(pk=request.session[CART_ID])
                cart.item_set.all().delete()
                cart.delete()
            except:
                pass
            messages.add_message(request, messages.SUCCESS, _("Your order was successful. Thanks for your business!"))

            return redirect("checkout_order_details", order.pk)
        else:
            order.update_status(OrderModel.PENDING_PAYMENT)
            messages.error(request, "We were unable to process your card for the following reason: {0}".format(data))

    context = {
        "order": order.order,
        "transaction": transaction,
    }

    if request.is_ajax():
        return render_to_response(
            ajax_template_name,
            context_instance=RequestContext(request, context)
        )

    return render_to_response(
        template_name,
        context_instance=RequestContext(request)
    )
"""


@login_required
def order_list(request, **kwargs):

    template_name = kwargs.pop("template_name", "checkout/order_list.html")
    orders = OrderModel.objects.filter(user=request.user).order_by('-creation_date')

    return render_to_response(template_name, {
        "orders": orders,
    }, context_instance=RequestContext(request))


@login_required
def order_details(request, pk, **kwargs):

    template_name = kwargs.pop("template_name", "checkout/order_detail.html")
    order = get_object_or_404(request.user.orders, pk=pk)
    if order.transactions.count():
        transaction = order.transactions.latest()
    else:
        transaction = None

    return render_to_response(template_name, {
        "order": order,
        "transaction": transaction
    }, context_instance=RequestContext(request))


@require_POST
def lookup_discount_code(request):
    try:
        discount = Discount.objects.get(code=request.POST.get("discount_code"))
        amount = discount.amount
    except:
        amount = 0
    return HttpResponse(json.dumps({"discount": str(amount)}), mimetype="application/json")
