"""Load the small, reviewed UK Government 2025 factor subset."""

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Organisation
from emissions.models import EmissionFactor

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "official_factors.json"


class Command(BaseCommand):
    help = "Seed reviewed UK Government 2025 factors into one explicit organisation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organisation-id",
            type=int,
            required=True,
            help="Primary key of the organisation receiving the factors.",
        )

    def handle(self, *args, **options):
        try:
            organisation = Organisation.objects.get(pk=options["organisation_id"])
        except Organisation.DoesNotExist as exc:
            raise CommandError("Organisation ID does not exist.") from exc

        dataset = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        prepared = [
            {key: value for key, value in entry.items() if key != "source_row"}
            | {
                "name": f"{entry['name']} ({entry['unit']})",
                "source": dataset["source"],
                "kg_per_unit": Decimal(entry["kg_per_unit"]),
                "is_demo": False,
            }
            for entry in dataset["factors"]
        ]
        created = 0
        skipped = 0
        with transaction.atomic():
            for values in prepared:
                matches = EmissionFactor.objects.filter(
                    organisation=organisation, name=values["name"], year=values["year"]
                )
                existing = list(matches)
                if existing:
                    same = len(existing) == 1 and all(
                        getattr(existing[0], key) == value for key, value in values.items()
                    )
                    if same:
                        skipped += 1
                        continue
                    raise CommandError(
                        f"Factor conflict for {values['name']} ({values['year']}); "
                        "existing factor was left unchanged."
                    )
                EmissionFactor.objects.create(organisation=organisation, **values)
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created}; skipped {skipped} identical."))
