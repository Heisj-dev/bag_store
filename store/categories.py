"""
The category list is read on every page (the menu, the filter buttons), and it
hardly ever changes, so it is kept for a minute instead of asking the database
every time. Saving or deleting a category in the admin clears it at once.
"""

from django.core.cache import cache

from .models import Category

CACHE_KEY = "all-categories"
CACHE_SECONDS = 60


def all_categories():
    """Every category, A to Z, as a list."""

    categories = cache.get(CACHE_KEY)

    if categories is None:
        categories = list(Category.objects.all())
        cache.set(CACHE_KEY, categories, CACHE_SECONDS)

    return categories


def forget_categories(**kwargs):
    cache.delete(CACHE_KEY)
