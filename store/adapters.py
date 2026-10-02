"""
django-allauth is only used for "Continue with Google". These adapters keep
that flow consistent with the rest of the shop:

* Google customers get username == e-mail, exactly like customers who register
  through the shop's own form.
* allauth's own "signed in / signed out" messages are silenced, because
  store/signals.py writes the shop's messages for every login method.
* A cancelled or failed Google sign-in sends the customer back to /login/ with
  a short message, instead of allauth's unbranded error page.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_email, user_username
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base.constants import AuthError


class AccountAdapter(DefaultAccountAdapter):

    def populate_username(self, request, user):

        email = (user_email(user) or "").strip().lower()

        User = get_user_model()

        if (
            email
            and len(email) <= 150
            and not User._default_manager.filter(username__iexact=email).exists()
        ):
            user_username(user, email)
            return

        super().populate_username(request, user)

    def add_message(
        self,
        request,
        level,
        message_template=None,
        message_context=None,
        extra_tags="",
        message=None,
    ):

        if message_template in {
            "account/messages/logged_in.txt",
            "account/messages/logged_out.txt",
        }:
            return

        super().add_message(
            request,
            level,
            message_template=message_template,
            message_context=message_context,
            extra_tags=extra_tags,
            message=message,
        )


class SocialAccountAdapter(DefaultSocialAccountAdapter):

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):

        super().on_authentication_error(
            request,
            provider,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )

        if error == AuthError.CANCELLED:
            messages.error(request, "GOOGLE SIGN-IN WAS CANCELLED.")
        else:
            messages.error(request, "GOOGLE SIGN-IN FAILED. PLEASE TRY AGAIN.")

        raise ImmediateHttpResponse(redirect("login"))
