import os
import csv
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockmanager.settings")

import django
django.setup()

from apps.catalogue.models import Article, Category
from apps.accounts.models import Site, User
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


    

