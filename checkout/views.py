from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render_to_response
from django.template import RequestContext
from django.utils.importlib import import_module
from django.utils.translation import ugettext_lazy as _

from django.contrib import messages
from django.contrib.auth.decorators import login_required

from cart.cart import CART_ID
from cart.models import Cart as CartModel

from checkout.models import Discount, Order as OrderModel, OrderTransaction
from checkout.order import Order, ORDER_ID, LineItemAlreadyExists
from checkout.forms import CustomItemForm, PaymentProfileForm
from checkout.signals import (pre_handle_billing_info, post_handle_billing_info,
                        pre_submit_for_settlement, post_submit_for_settlement)
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
        "tax": 0,
        "total": 0
    }

    billing_data = None
    if request.method == "POST" and (
        request.POST.get("item_description") or request.POST.get("custom_confirm")
        ):
        checkout_summary["method"] = "custom"
        custom_form = CustomItemForm(request.POST)
        order = None
        if custom_form.is_valid():
            checkout_summary["items"].append({
                "description": custom_form.cleaned_data["item_description"],
                "amount": custom_form.cleaned_data["item_amount"],
                "attributes": custom_form.cleaned_data["item_attributes"]
            })
            checkout_summary["tax"] = custom_form.tax()
            checkout_summary["total"] = custom_form.total()

    if checkout_summary["method"] == "cart":
        # Look for cart in session
        # The cart remains active until order is completed
        try:
            cart = CartModel.objects.get(pk=request.session[CART_ID])
            checkout_summary["items"] = cart.item_set.all()
            checkout_summary["total"] = cart.total
        except:
            cart = None

        # Look for an order in process
        order = None

        if request.session.get(ORDER_ID):
            try:
                order = OrderModel.objects.get(user=request.session[ORDER_ID])
            except OrderModel.DoesNotExist:
                del request.session[ORDER_ID]

        if not order:
            try:
                order = OrderModel.objects.incomplete().get(user=request.user)
            except:
                pass

        # be helpful and look for stored billing data to autopop with
        if order and order.transactions.count():
            billing_data = order.transactions.latest()

        # No cart and no order == cya
        if not order and (not cart or not cart.item_set.count()):
            return redirect(empty_cart_url)

    if not request.user.is_authenticated():
        # @@ to do: if combo_form_class == None, use login_required approach
        Form = signup_form_class
    else:
        Form = payment_form_class

    if request.method == "POST" and (
        checkout_summary["method"] == "cart" or request.POST.get("custom_confirm")
    ):
        form = Form(request.POST)
        if form.is_valid():
            if not request.user.is_authenticated():
                user = form.save(request)
                form.login(request, user)
                # grab payment form class
                form = payment_form_class()

            else:
                # create order instance
                order = Order(request)
                request.session[ORDER_ID] = order.order.id

                # clean up any old incomplete orders
                for abandoned in OrderModel.objects.filter(
                        user=request.user
                    ).exclude(pk=order.order.pk).filter(
                        Q(status=OrderModel.PENDING_PAYMENT) | Q(status=OrderModel.INCOMPLETE)
                    ):
                    for item in abandoned.items.all():
                        item.delete()
                    abandoned.delete()

                for item in checkout_summary["items"]:
                    try:
                        order.add(item.unit_price, product=item.product, attributes=item.attributes)
                    except LineItemAlreadyExists:
                        pass
                    except AttributeError:
                        order.add(item["amount"], attributes=item["attributes"], description=item["description"])

                if form.cleaned_data.get("discount_code"):
                    order.apply_discount(code=form.cleaned_data["discount_code"])

                pp = payment_module.Processor()

                payment_data = form.cleaned_data
                payment_data.update({
                    "email": request.user.email,
                    "first_name": request.user.first_name,
                    "last_name": request.user.last_name,
                })

                pre_handle_billing_info.send(
                    sender=None,
                    user=request.user,
                    payment_data=payment_data
                )

                success, reference_id, error, results = pp.handle_billing_info(
                    payment_data, amount=order.get_total()
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

                    OrderTransaction.objects.create(
                        order=order.order,
                        amount=order.get_total(),
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

                    return redirect("checkout_confirm")

                else:
                    form._errors.update({"__all__": [error, ]})
    else:
        form = Form()
        if request.user.is_authenticated():
            if billing_data:
                for field in form.fields:
                    if billing_data.get(field):
                        field.initial = billing_data.get(field)
            else:
                form.fields["billing_first_name"].initial = request.user.first_name
                form.fields["billing_last_name"].initial = request.user.last_name

    return render_to_response(template_name, {
        "form": form,
        "checkout_summary": checkout_summary,
        "order": order
    }, context_instance=RequestContext(request))


def confirm(request):
    try:
        order = request.user.orders.pending_payment()[0]
        transaction = order.transactions.latest()
    except:
        return redirect("checkout")

    if request.method == "POST":

        pp = payment_module.Processor()

        pre_submit_for_settlement.send(
            sender=None,
            order=order,
            transaction=transaction
        )

        success, data = pp.submit_for_settlement(order, reference_id=transaction.reference_number)

        # NOTE: if trans failed, data == error code + verbose error message

        transaction.received_data = str(data)
        if success:
            transaction.status = transaction.COMPLETE
        else:
            transaction.status = transaction.FAILED
        transaction.save()

        post_submit_for_settlement.send(
            sender=None,
            order=order,
            transaction=transaction,
            success=success,
            data=data
        )

        if success:
            order.status = OrderModel.COMPLETE
            order.save()
            messages.add_message(request, messages.SUCCESS, _("Your order was successful. Thanks for your business!"))

            return redirect("checkout_order_details", [order.pk])
        else:
            order.status = OrderModel.PENDING_PAYMENT
            order.save()
            messages.add_message(request, messages.ERROR, data)

    return render_to_response("checkout/confirm.html", {
        "order": order,
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
