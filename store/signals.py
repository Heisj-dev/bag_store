from django.contrib import messages
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from allauth.account.signals import user_signed_up


# One place for the shop's authentication messages, whichever way the
# customer signs in (login form, registration form, Google) or out.

@receiver(user_signed_up)
def remember_new_google_customer(sender, request, user, **kwargs):
    """allauth sends this only for brand-new Google customers."""
    request._new_social_customer = True


@receiver(user_logged_in)
def show_customer_login_message(sender, request, user, **kwargs):
    """Show one short success message after a customer signs in."""

    if request is None:
        return

    path = request.path

    if path == "/accounts/register/":
        messages.success(request, "ACCOUNT CREATED SUCCESSFULLY.")

    elif path.startswith("/accounts/google/"):
        if getattr(request, "_new_social_customer", False):
            messages.success(request, "ACCOUNT CREATED SUCCESSFULLY.")
        else:
            messages.success(request, "SUCCESSFULLY LOGGED IN.")

    elif path in {"/login/", "/accounts/login/"}:
        messages.success(request, "SUCCESSFULLY LOGGED IN.")


@receiver(user_logged_out)
def show_customer_logout_message(sender, request, user, **kwargs):
    """Confirm a logout from the shop's own logout button."""

    if request is not None and user is not None and request.path == "/accounts/logout/":
        messages.success(request, "SUCCESSFULLY LOGGED OUT.")

# Customer order-status emails. These fire whenever an Order is saved with a
# new status, including changes made from Django admin.
from django.db.models.signals import pre_save, post_save

from .models import Order
from .emails import (
    send_order_confirmed_email,
    send_order_shipped_email,
    send_order_delivered_email,
    send_order_cancelled_email,
)


_STATUS_EMAILS = {
    "CONFIRMED": send_order_confirmed_email,
    "SHIPPED": send_order_shipped_email,
    "DELIVERED": send_order_delivered_email,
    "CANCELLED": send_order_cancelled_email,
}


@receiver(pre_save, sender=Order)
def _stash_previous_order_status(sender, instance, **kwargs):
    if instance.pk:
        instance._previous_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )
    else:
        instance._previous_status = None


@receiver(post_save, sender=Order)
def _email_customer_on_status_change(sender, instance, created, **kwargs):
    if created:
        return

    previous_status = getattr(instance, "_previous_status", None)

    if previous_status == instance.status:
        return

    send_email = _STATUS_EMAILS.get(instance.status)

    if send_email:
        send_email(instance)

