import os
import csv
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockmanager.settings")

import django
django.setup()

from apps.catalogue.models import Article
from django.db import transaction


articles = []

with transaction.atomic():
    with open("articles.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            Article.objects.create(
                name=row["name"],
                category_id=row["category_id"],
                unit=row["unit"]
            )

