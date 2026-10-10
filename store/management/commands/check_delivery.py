"""
Try the delivery calculation on one address, from your own computer.

    python manage.py check_delivery "Plot 12 Kosovo Road" "Makindye"

This makes REAL calls to Geoapify (2 requests, from your free allowance) and
changes nothing in the database. It never prints the API key.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from store.delivery import FIXED_FEE_LIMIT_M, calculate_delivery, describe_matches


class Command(BaseCommand):
    help = "Show the delivery distance and fee for an address (live Geoapify call)."

    def add_arguments(self, parser):
        parser.add_argument("address", help="Street address or landmark")
        parser.add_argument("city", nargs="?", default="Kampala", help="City / area")
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Also show what the map service returned (one more live call).",
        )

    def handle(self, *args, **options):
        if not settings.GEOAPIFY_API_KEY:
            self.stdout.write(
                self.style.WARNING(
                    "GEOAPIFY_API_KEY is not set. Add it to your .env file first."
                )
            )

        result = calculate_delivery(options["address"], options["city"])

        self.stdout.write(f"Address : {options['address']}, {options['city']}")
        self.stdout.write(f"Status  : {result.status}")

        if result.distance_m is not None:
            self.stdout.write(
                f"Distance: {result.distance_m} m ({result.distance_km} km by road)"
            )

        if result.status == "CALCULATED":
            self.stdout.write(self.style.SUCCESS(f"Fee     : UGX {result.fee:,.0f}"))
        elif result.status == "QUOTE_REQUIRED":
            self.stdout.write(
                self.style.WARNING(
                    f"Fee     : none. Over {FIXED_FEE_LIMIT_M / 1000:g} km: "
                    "customer is phoned."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Fee     : none. Could not verify ({result.problem}): "
                    "customer is phoned."
                )
            )

        if result.approximate:
            self.stdout.write("Approx  : yes (priced from the middle of an area or town)")

        self.stdout.write(f"Note    : {result.note}")

        if options["raw"]:
            matches, error = describe_matches(options["address"], options["city"])
            self.stdout.write("")
            self.stdout.write("Raw matches from the map service:")
            if error:
                self.stdout.write(f"  (none: {error})")
            for m in matches:
                self.stdout.write(
                    f"  - {m['formatted']}\n"
                    f"      type={m['result_type']}  "
                    f"confidence={m['confidence']}  match={m['match_type']}"
                )
