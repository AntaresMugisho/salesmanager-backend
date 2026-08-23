import os
import csv
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockmanager.settings")

import django
django.setup()

from apps.catalogue.models import Article, Category
from apps.accounts.models import Site, User
from apps.stock.models import StockLevel
from django.db import transaction


with transaction.atomic():
    with open("sites.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            Site.objects.create(**row)

    with open("categories.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            Category.objects.create(name=row["name"], id=row["id"])

    with open("articles.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter=';')

        for row in reader:
            Article.objects.create(
                name=row["name"],
                category_id=row["category_id"],
                unit=row["unit"]
            )

    # Every article gets a level at every site, because the rest of the app
    # assumes one exists: the API creates it alongside the article, and a
    # threshold saved against a row that was never written used to vanish
    # without an error. Quantity stays 0 — stock arrives through movements.
    StockLevel.objects.bulk_create(
        [
            StockLevel(article=article, site=site)
            for article in Article.objects.all()
            for site in Site.objects.all()
        ],
        ignore_conflicts=True,
    )


    

