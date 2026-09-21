from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("bag/<int:bag_id>/", views.product_detail, name="product_detail"),
    path("cart/add/<int:bag_id>/", views.cart_add, name="cart_add"),
    path("cart/", views.cart_detail, name="cart_detail"),
    path("cart/increase/<int:bag_id>/", views.cart_increase, name="cart_increase"),
    path("cart/decrease/<int:bag_id>/", views.cart_decrease, name="cart_decrease"),
    path("cart/remove/<int:bag_id>/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<str:order_number>/",views.order_confirmation,name="order_confirmation"),
    path("orders/",views.order_history,name="order_history"),
    
]