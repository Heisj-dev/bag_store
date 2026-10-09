from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("collection/", views.collection, name="collection"),
    path("bag/<int:bag_id>/", views.product_detail, name="product_detail"),
    path(
        "bag/<int:bag_id>/<slug:slug>/",
        views.product_detail,
        name="product_detail_slug",
    ),
    path("category/<slug:slug>/", views.category_page, name="category_page"),

    path("cart/add/<int:bag_id>/", views.cart_add, name="cart_add"),
    path("cart/", views.cart_detail, name="cart_detail"),
    path("cart/increase/<int:bag_id>/", views.cart_increase, name="cart_increase"),
    path("cart/decrease/<int:bag_id>/", views.cart_decrease, name="cart_decrease"),
    path("cart/remove/<int:bag_id>/", views.cart_remove, name="cart_remove"),

    path("checkout/", views.checkout, name="checkout"),

    path(
        "order/<str:order_number>/",
        views.order_confirmation,
        name="order_confirmation",
    ),

    path(
        "orders/",
        views.order_history,
        name="order_history",
    ),

    path("login/", views.login_view, name="login"),

    path("privacy/", views.privacy, name="privacy"),

    path("v/", views.record_visit, name="record_visit"),

    path("healthz/", views.healthz, name="healthz"),

    path("robots.txt", views.robots_txt, name="robots_txt"),

    path("sitemap.xml", views.sitemap, name="sitemap"),

    path("social-card.png", views.social_card, name="social_card"),

    path("logo-<int:width>.webp", views.logo_image, name="logo_image"),

    path(
        "favicon.ico",
        views.site_icon,
        {"filename": "favicon.ico"},
        name="favicon",
    ),

    path(
        "apple-touch-icon.png",
        views.site_icon,
        {"filename": "apple-touch-icon.png"},
        name="apple_touch_icon",
    ),
]