from django.urls import path
from django.contrib.auth import views as auth_views

from . import views


urlpatterns = [

    # Registration
    path(
        "register/",
        views.register,
        name="register"
    ),

    # Login
    path(
        "login/",
        views.login_view,
        name="login"
    ),

    # Logout
    path(
        "logout/",
        auth_views.LogoutView.as_view(
            next_page="index"
        ),
        name="logout"
    ),

    # Password reset - request
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="store/password_reset.html"
        ),
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