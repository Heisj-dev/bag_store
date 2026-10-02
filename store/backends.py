"""
Authentication backend that lets a customer log in with their e-mail address.

Customers created through the shop's own registration form have username == email,
so the default ModelBackend already works for them. Customers created through
"Continue with Google" (or any account whose username differs from its e-mail)
would not be found that way, so this backend looks the account up by e-mail
(case-insensitively).

ModelBackend stays in AUTHENTICATION_BACKENDS, so the Django admin keeps working
with usernames.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):

        email = (kwargs.get("email") or username or "").strip()

        if not email or password is None:
            return None

        User = get_user_model()

        users = User._default_manager.filter(email__iexact=email).order_by("id")

        for user in users:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user

        if not users:
            # Same cost as a real check, so response time does not reveal
            # whether an account exists for this e-mail.
            User().set_password(password)

        return None
