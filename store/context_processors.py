from django.conf import settings

from .categories import all_categories
from .cart import Cart


def store_globals(request):

    nav_categories = all_categories()

    cart = Cart(request)
    cart_count = cart.count()

    return {
        "nav_categories": nav_categories,
        "cart_count": cart_count,
        "google_verification": settings.GOOGLE_SITE_VERIFICATION,
        "bing_verification": settings.BING_SITE_VERIFICATION,
    }