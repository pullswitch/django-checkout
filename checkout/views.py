import json

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render_to_response
from django.template import RequestContext
from django.utils.importlib import import_module
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_POST

from django.contrib import messages
from django.contrib.auth.decorators import login_required

from cart.cart import CART_ID
from cart.models import Cart as CartModel

from checkout.models import Discount, Order as OrderModel, OrderTransaction
from checkout.order import Order, ORDER_ID
from checkout.forms import CustomItemForm, PaymentProfileForm
from checkout.signals import (pre_handle_billing_info, post_handle_billing_info,
                        pre_charge, post_charge,
                        pre_subscribe, post_subscribe, order_complete)
from checkout.utils import import_from_string

payment_module = import_module(getattr(settings, "CHECKOUT_PAYMENT_PROCESSOR", "checkout.processors.braintree_processor"))
SignupForm = import_from_string(
    getattr(settings,
        "CHECKOUT_SIGNUP_FORM",
        "checkout.forms.CheckoutSignupForm"
    )
)


def info(request,
    payment_form_class=PaymentProfileForm,
    signup_form_class=SignupForm,
    empty_cart_url="cart", **kwargs):

    template_name = kwargs.get("template_name", "checkout/form.html")

    checkout_summary = {
        "method": "cart",
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
        checkout_summary["discount"] = order.order.discount

    if request.method == "POST":
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
        elif request.POST.get("subscription") and getattr(settings, "CHECKOUT_SUBSCRIPTIONS", False):
            plan = settings.CHECKOUT_SUBSCRIPTIONS[request.POST.get("subscription")]
            checkout_summary["method"] = "subscription"
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
        if SignupForm:
            signup_form = SignupForm(request.POST)
            if signup_form.is_valid() and not request.user.is_authenticated():
                try:
                    user = signup_form.save()
                except:
                    user = signup_form.create_user()
                signup_form.login(request, user)

        form = Form(request.POST)
        if request.user.is_authenticated():

            # create order instance
            if not order:
                print "creating order"
                order = Order(request)
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
                if order.order.discount:
                    checkout_summary["discount"] = order.order.discount
                    checkout_summary["total"] -= order.order.discount
                    OrderTransaction.objects.get_or_create(
                        order=order.order,
                        amount=order.order.discount,
                        payment_method=OrderTransaction.DISCOUNT,
                        reference_number=order.order.discount_code
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

                if order.order.total > 0 and form.is_valid():

                    pp = payment_module.Processor()

                    payment_data = form.cleaned_data
                    payment_data.update({
                        "email": request.user.email,
                        "first_name": request.user.first_name,
                        "last_name": request.user.last_name,
                    })

                    customer_id = None
                    print "PRE HANDLE BILLING ============", customer_id
                    pre_handle_billing_info.send(
                        sender=None,
                        user=request.user,
                        payment_data=payment_data,
                        customer_id=customer_id
                    )
                    print "POST SIGNAL"
                    print customer_id

                    success, reference_id, error, results = pp.create_customer(
                        payment_data, customer_id=customer_id
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

                        OrderTransaction.objects.get_or_create(
                            order=order.order,
                            amount=order.order.total,
                            payment_method=OrderTransaction.CREDIT,
                            last_four=form.cleaned_data["card_number"][-4:],
                            reference_number=reference_id,
                            billing_first_name=form.cleaned_data["billing_first_name"],
                            billing_last_name=form.cleaned_data["billing_last_name"],
                            billing_address1=form.cleaned_data["address1"],
                            billing_address2=form.cleaned_data["address2"],
                            billing_city=form.cleaned_data["city"],
                            billing_region=form.cleaned_data["region"],
                            billing_postal_code=form.cleaned_data["postal_code"],
                            billing_country=form.cleaned_data["country"],
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
                form.fields["billing_first_name"].initial = request.user.first_name
                form.fields["billing_last_name"].initial = request.user.last_name
        else:
            signup_form = SignupForm()

    return render_to_response(template_name, {
        "form": form,
        "signup_form": signup_form,
        "checkout_summary": checkout_summary,
        "order": order
    }, context_instance=RequestContext(request))


def confirm(request):
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
                pre_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction
                )
                post_subscribe.send(
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

                pre_subscribe.send(
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

                post_subscribe.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction,
                    data=data,
                    request=request
                )
            else:
                pre_charge.send(
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

                post_charge.send(
                    sender=None,
                    order=order.order,
                    transaction=transaction,
                    success=success,
                    data=data
                )

        if success:
            order.update_status(OrderModel.COMPLETE)
            order_complete.send(sender=None, order=order.order)
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
            messages.add_message(request, messages.ERROR, data)

    return render_to_response("checkout/confirm.html", {
        "order": order.order,
        "transaction": transaction,
    }, context_instance=RequestContext(request))


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
    transaction = order.transactions.latest()

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
