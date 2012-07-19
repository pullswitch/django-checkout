import json
from decimal import Decimal

from django.core.urlresolvers import reverse
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
    success_url = "checkout_confirm"
    messages = {
        "customer_info_error": {
            "level": messages.ERROR,
            "text": _("The payment information could not be validated")
        }
    }

    def get(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)
        if (not self.request.user.is_authenticated() and
            not CHECKOUT["ANONYMOUS_CHECKOUT"]):
            self.form_class = self.form_class_signup
        return super(CheckoutView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.order_obj = Order(self.request)
        if (not self.request.user.is_authenticated() and
            not CHECKOUT["ANONYMOUS_CHECKOUT"]):
            self.form_class = self.form_class_signup
        incoming = self.retrieve_item()

        if self.request.POST.get("discount_code"):
            self.order_obj.apply_discount(self.request.POST.get("discount_code"))
            if self.order_obj.total == 0:
                self.order_obj.update_status(OrderModel.PENDING_PAYMENT)
                # goal: remove payment-related requirements if
                # no payment is necessary
                for field in self.form_class.base_fields.keys():
                    if field in PaymentForm.base_fields.keys():
                        self.form_class.base_fields[field].required = False

        return self.post_handler(incoming, *args, **kwargs)

    def post_handler(self, incoming, *args, **kwargs):
        if incoming:
            form = self.get_form_class()(initial=self.get_initial())
            return self.render_to_response(self.get_context_data(form=form))
        elif not self.order_obj.order.items.count():
            return redirect(self.empty_redirect)

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
        if self.request.user.is_authenticated():
            initial.update({
                "billing_first_name": self.request.user.first_name,
                "billing_last_name": self.request.user.last_name
            })
        initial["amount"] = self.order_obj.total
        if self.order_obj.get_transactions().count():
            billing_data = self.order_obj.get_transactions().latest()
            for field_name in self.form_class().fields:
                if hasattr(billing_data, field_name):
                    initial[field_name] = getattr(billing_data, field_name)
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

        if (not self.request.user.is_authenticated() and
            not CHECKOUT["ANONYMOUS_CHECKOUT"]):
            user = self.create_user(form)
            user = auth.authenticate(
                username=user.username,
                password=form.cleaned_data["password"]
            )
            auth.login(self.request, user)
            self.order_obj.order.user = user
            self.order_obj.order.save()
            self.after_signup(user, form)

        if self.request.user.is_authenticated():
            form.cleaned_data.update({
                "email": self.request.user.email,
                "first_name": self.request.user.first_name,
                "last_name": self.request.user.last_name,
            })

        # if payment is needed
        if self.order_obj.order.total > 0:
            success = self.save_customer_info(form)
        else:  # no payment needed, e.g. full discount
            success = True
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

    def after_signup(self, user, form):
        signals.user_signed_up.send(sender=SignupForm, user=user, form=form)

    def save_customer_info(self, form):
        payment_data = form.cleaned_data
        if self.request.user.is_authenticated():
            payment_data.update({
                "email": self.request.user.email,
                "first_name": self.request.user.first_name,
                "last_name": self.request.user.last_name,
            })

        success, reference_id, error, results = self.processor.create_customer(
            payment_data,
            customer_id=self.order_obj.order.customer_id
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
            self.order_obj.order.customer_id = reference_id
            self.order_obj.order.save()
            card_details = self.processor.get_customer_card(reference_id)

            OrderTransaction.objects.get_or_create(
                order=self.order_obj.order,
                amount=self.order_obj.order.total,
                payment_method=OrderTransaction.CREDIT,
                last_four=self.processor.get_card_last4(card_details),
                reference_number=reference_id,
                billing_first_name=form.cleaned_data.get("billing_first_name") or\
                    form.cleaned_data.get("first_name") or\
                    self.request.user.first_name,
                billing_last_name=form.cleaned_data.get("billing_last_name") or\
                    form.cleaned_data.get("last_name") or \
                    self.request.user.last_name,
                billing_address1=form.cleaned_data.get("billing_address1", ""),
                billing_address2=form.cleaned_data.get("billing_address2", ""),
                billing_city=form.cleaned_data.get("billing_city", ""),
                billing_region=form.cleaned_data.get("billing_region", ""),
                billing_postal_code=form.cleaned_data.get("billing_postal_code", ""),
                billing_country=form.cleaned_data.get("billing_country", ""),
            )

            self.order_obj.update_totals()
            self.order_obj.update_status(OrderModel.PENDING_PAYMENT)
            return True
        return False


class SubscribeView(CheckoutView):

    method = "subscription"

    def retrieve_item(self):
        sf = SubscriptionForm(self.request.POST)
        if sf.is_valid() or (
            CHECKOUT["ALLOW_PLAN_CREATION"] and
            self.request.POST.get("amount")
        ):
            plan = None
            if CHECKOUT["SUBSCRIPTIONS"] and (
                self.request.POST.get("subscription") in CHECKOUT["SUBSCRIPTIONS"]
            ):
                plan = CHECKOUT["SUBSCRIPTIONS"][
                    self.request.POST.get("subscription")
                ]
            if not plan and CHECKOUT["ALLOW_PLAN_CREATION"]:
                plan_opts = CHECKOUT["PLAN_OPTIONS_GENERATOR"](
                    Decimal(self.request.POST.get("amount"))
                )
                plan = self.processor.create_plan(**plan_opts)
            if plan:
                self.order_obj.clear()
                self.order_obj.add(
                    plan["amount"],
                    description=plan["name"],
                    subscription_plan=plan["plan_id"]
                )
                self.order_obj.update_totals()
                return True
        return False


class CartCheckoutView(CheckoutView):

    method = "cart"

    def get(self, *args, **kwargs):
        from cart.cart import CART_ID
        from cart.models import Cart as CartModel

        self.order_obj = Order(self.request)
        # clear pre-existing items
        self.order_obj.clear()
        if CART_ID in self.request.session:
            cart = CartModel.objects.get(pk=self.request.session[CART_ID])
            for item in cart.item_set.all():
                try:
                    self.order_obj.add(
                        item.unit_price,
                        product=item.product,
                        attributes=item.attributes
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
        return super(CartCheckoutView, self).get(*args, **kwargs)

    def retrieve_item(self):
        # items aren't added via post to this view
        return False


class ConfirmView(TemplateView):

    template_name = "checkout/confirm.html"
    template_name_ajax = "checkout/confirm.html"
    processor = payment_module.Processor()
    success_url = "checkout_confirm"  # redirects to order page
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
        try:
            self.transaction = self.order_obj.get_transactions().latest()
        except:
            # this may not be acceptable
            self.transaction = None
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
            self.transaction.status = self.transaction.COMPLETE
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

            return redirect(self.get_success_url(self.order_obj.pk))

        return self.render_to_response(self.get_context_data())

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

    def get_success_url(self, pk):
        return reverse("checkout_order_details", kwargs={"pk": pk})


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
        if "cart_count" in self.request.session:
            del self.request.session["cart_count"]


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
    amount = 0
    try:
        discount = Discount.objects.get(
            code__iexact=request.POST.get("discount_code")
        )
        if discount.is_valid():
            # @@ what if it's a percentage discount?
            amount = discount.amount
    except:
        pass
    return HttpResponse(json.dumps({"discount": str(amount)}), mimetype="application/json")
