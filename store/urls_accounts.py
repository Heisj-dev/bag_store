from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

from . import views


urlpatterns = [

    # Registration
    path(
        "register/",
        views.register,
        name="register"
    ),

    # allauth's own pages are not used by the shop. Anyone arriving at one
    # (an old link, a bookmark, a redirect from allauth) is sent to the
    # shop's page instead. The main login is /login/ (see store/urls.py).
    path(
        "login/",
        RedirectView.as_view(pattern_name="login", query_string=True),
        name="legacy_login"
    ),

    path(
        "signup/",
        RedirectView.as_view(pattern_name="register", query_string=True),
        name="legacy_signup"
    ),

    path(
        "password/reset/",
        RedirectView.as_view(pattern_name="password_reset"),
        name="legacy_password_reset"
    ),

    # Logout
    path(
        "logout/",
        views.CustomerLogoutView.as_view(),
        name="logout"
    ),

    # Password reset - request
    path(
        "password-reset/",
        views.CustomerPasswordResetView.as_view(),
        name="password_reset"
    ),

    # Password reset - email sent
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="store/password_reset_done.html"
        ),
        name="password_reset_done"
    ),

    # Password reset - new password
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="store/password_reset_confirm.html"
        ),
        name="password_reset_confirm"
    ),

    # Password reset - complete
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="store/password_reset_complete.html"
        ),
        name="password_reset_complete"
    ),

    # Customer Account
    path(
        "account/",
        views.account,
        name="account"
    ),

    # Orders
    path(
        "orders/",
        views.order_history,
        name="order_history"
    ),

    # Change Password
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="store/password_change.html",
            success_url="/accounts/password/change/done/"
        ),
        name="password_change"
    ),

    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="store/password_change_done.html"
        ),
        name="password_change_done"
    ),
]