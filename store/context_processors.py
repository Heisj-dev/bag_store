from .models import Category
from .cart import Cart


def store_globals(request):

    nav_categories = Category.objects.all()

    cart = Cart(request)
    cart_count = sum(item["quantity"] for item in cart)

    return {
        "nav_categories": nav_categories,
        "cart_count": cart_count,
    }