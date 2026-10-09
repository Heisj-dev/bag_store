from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from store.analytics import KEEP_DAYS
from store.models import VisitEvent


class Command(BaseCommand):
    help = "Delete visitor statistics older than a number of days (default 400)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=KEEP_DAYS)

    def handle(self, *args, **options):

        oldest = timezone.localdate() - timedelta(days=options["days"])

        deleted, _ = VisitEvent.objects.filter(day__lt=oldest).delete()

        self.stdout.write(f"Deleted {deleted} visitor events older than {oldest}.")
