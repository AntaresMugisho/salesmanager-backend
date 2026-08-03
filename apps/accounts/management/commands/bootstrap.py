"""Bring a fresh database to a working login.

Idempotent: re-running against a populated database reports what exists and
changes nothing. Exists so a fresh clone does not need the admin to get
started, and so `Site.objects.current()` never raises in a real deployment.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Site, User


class Command(BaseCommand):
    help = "Create the site and the first owner account."

    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--full-name")
        parser.add_argument("--password")
        parser.add_argument("--site-name")
        parser.add_argument("--site-address")

    def handle(self, *args, **options):
        with transaction.atomic():
            self._ensure_site(options)
            self._ensure_owner(options)

    def _ask(self, options, key, prompt, secret=False):
        value = options.get(key)
        if value:
            return value
        if secret:
            from getpass import getpass

            value = getpass(f"{prompt} : ")
        else:
            value = input(f"{prompt} : ")
        value = value.strip()
        if not value:
            raise CommandError(f"{prompt} est obligatoire.")
        return value

    def _ensure_site(self, options):
        if Site.objects.exists():
            self.stdout.write(
                f"Établissement déjà configuré : {Site.objects.current().name}"
            )
            return
        site = Site.objects.create(
            name=self._ask(options, "site_name", "Nom de l'établissement"),
            address=self._ask(options, "site_address", "Adresse"),
        )
        self.stdout.write(self.style.SUCCESS(f"Établissement créé : {site.name}"))

    def _ensure_owner(self, options):
        if User.objects.filter(role=User.Role.OWNER, is_active=True).exists():
            self.stdout.write("Un propriétaire actif existe déjà.")
            return

        email = self._ask(options, "email", "Adresse e-mail du propriétaire")
        full_name = self._ask(options, "full_name", "Nom complet")
        password = self._ask(options, "password", "Mot de passe", secret=True)

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        owner = User.objects.create_superuser(
            email=email, full_name=full_name, password=password
        )
        self.stdout.write(self.style.SUCCESS(f"Propriétaire créé : {owner.email}"))
