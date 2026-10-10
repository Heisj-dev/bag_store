"""
Try the address suggestions from your own computer, as a customer would see them.

    python manage.py check_suggestions "kyanja"

This makes ONE real call to Geoapify (from your free allowance) and changes
nothing. It never prints the API key or the signed tokens.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from store.delivery import SUGGEST_MIN_CHARS, suggest_places


class Command(BaseCommand):
    help = "Show the address suggestions for some typed text (live Geoapify call)."

    def add_arguments(self, parser):
        parser.add_argument("text", help="What a customer might have typed so far")

    def handle(self, *args, **options):
        text = options["text"]

        if not settings.GEOAPIFY_API_KEY:
            self.stdout.write(
                self.style.WARNING("GEOAPIFY_API_KEY is not set. Add it to your .env file first.")
            )
            return

        if len(text.replace(" ", "")) < SUGGEST_MIN_CHARS:
            self.stdout.write(
                self.style.WARNING(
                    f"Type at least {SUGGEST_MIN_CHARS} letters: shorter text is not searched."
                )
            )
            return

        found = suggest_places(text)

        self.stdout.write(f"Typed: {text}")

        if not found:
            self.stdout.write(
                self.style.WARNING(
                    "No suggestions. Either nothing matches, or the lookup failed "
                    "(a warning above says why). Customers can still type a full address."
                )
            )
            return

        for number, suggestion in enumerate(found, start=1):
            city = f"   (city box would be filled with: {suggestion['city']})" if suggestion["city"] else ""
            self.stdout.write(f"  {number}. {suggestion['label']}{city}")
