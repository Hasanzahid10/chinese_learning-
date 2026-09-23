import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from dictionary.models import HSKWord


class Command(BaseCommand):
    help = "Import one HSK level JSON file into PostgreSQL"

    def add_arguments(self, parser):
        parser.add_argument(
            "hsk_level",
            type=int,
            choices=[1, 2, 3, 4, 5, 6],
            help="HSK level to import (1-6)",
        )

    def handle(self, *args, **options):
        hsk_level = options["hsk_level"]

        # ----------------------------------------------------
        # JSON FILE
        # ----------------------------------------------------

        json_path = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "hsk_json"
            / f"hsk-{hsk_level}.json"
        )

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write(
            self.style.HTTP_INFO(
                f"HSK {hsk_level} IMPORT"
            )
        )
        self.stdout.write("=" * 70)

        self.stdout.write(
            f"JSON file:\n{json_path}"
        )

        # ----------------------------------------------------
        # CHECK FILE
        # ----------------------------------------------------

        if not json_path.exists():
            raise CommandError(
                f"JSON file not found:\n{json_path}"
            )

        # ----------------------------------------------------
        # READ JSON
        # ----------------------------------------------------

        try:
            with open(
                json_path,
                "r",
                encoding="utf-8",
            ) as f:
                data = json.load(f)

        except json.JSONDecodeError as e:
            raise CommandError(
                f"Invalid JSON file:\n{e}"
            )

        if not isinstance(data, list):
            raise CommandError(
                "JSON must contain a list of HSK entries."
            )

        self.stdout.write(
            f"Found {len(data)} JSON entries."
        )

        # ----------------------------------------------------
        # PREPARE DATA
        # ----------------------------------------------------

        words_to_create = []

        skipped = 0

        for index, item in enumerate(data, start=1):

            try:
                chinese = str(
                    item["Chinese"]
                ).strip()

                pinyin = str(
                    item["Pinyin"]
                ).strip()

                english = str(
                    item["EN"]
                ).strip()

                bangla = str(
                    item["BN"]
                ).strip()

                # Make sure the JSON level matches
                # the level being imported.
                json_level = int(
                    item["hsk_level"]
                )

                if json_level != hsk_level:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping entry #{index}: "
                            f"JSON says HSK {json_level}, "
                            f"expected HSK {hsk_level}"
                        )
                    )
                    skipped += 1
                    continue

                if not chinese:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping entry #{index}: "
                            "Chinese is empty"
                        )
                    )
                    skipped += 1
                    continue

                words_to_create.append(
                    HSKWord(
                        hsk_level=hsk_level,
                        chinese=chinese,
                        pinyin=pinyin,
                        english=english,
                        bangla=bangla,
                    )
                )

            except KeyError as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping entry #{index}: "
                        f"missing field {e}"
                    )
                )
                skipped += 1

            except (ValueError, TypeError) as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping entry #{index}: {e}"
                    )
                )
                skipped += 1

        # ----------------------------------------------------
        # NOTHING TO IMPORT
        # ----------------------------------------------------

        if not words_to_create:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "No valid entries to import."
                )
            )
            return

        # ----------------------------------------------------
        # IMPORT
        # ----------------------------------------------------

        created = 0

        for start in range(
            0,
            len(words_to_create),
            1000,
        ):
            batch = words_to_create[
                start:start + 1000
            ]

            HSKWord.objects.bulk_create(
                batch,
                batch_size=1000,
                ignore_conflicts=True,
            )

            created += len(batch)

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        self.stdout.write("")
        self.stdout.write("-" * 70)
        self.stdout.write("RESULT")
        self.stdout.write("-" * 70)

        self.stdout.write(
            f"HSK level         : {hsk_level}"
        )

        self.stdout.write(
            f"JSON entries      : {len(data)}"
        )

        self.stdout.write(
            f"Prepared entries  : {len(words_to_create)}"
        )

        self.stdout.write(
            f"Skipped entries   : {skipped}"
        )

        self.stdout.write(
            f"Processed         : {created}"
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"HSK {hsk_level} import completed!"
            )
        )

        self.stdout.write("=" * 70)
        self.stdout.write("")