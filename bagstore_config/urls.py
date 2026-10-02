"""
URL configuration for bagstore_config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path("admin/", admin.site.urls),

    # The shop: /login/ is the main customer login.
    path("", include("store.urls")),

    # The shop's own account pages: register, logout, password reset/change,
    # account, orders. Listed before allauth so these always win.
    path("accounts/", include("store.urls_accounts")),

    # django-allauth, used only for Google sign-in:
    #   /accounts/google/login/            starts the Google sign-in
    #   /accounts/google/login/callback/   where Google sends the customer back
    # (the callback address is the one registered in the Google console).
    # Its own login / signup / password pages are redirected to the shop's
    # pages in store/urls_accounts.py.
    path("accounts/", include("allauth.urls")),
]
