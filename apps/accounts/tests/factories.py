"""Shared test factories.

Every later sub-project imports these rather than rolling its own users and
site, so their signatures are effectively public. `SiteFactory` is a
`django_get_or_create` on `is_default` because only one Site may exist.
"""

import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import Site, User


class SiteFactory(DjangoModelFactory):
    class Meta:
        model = Site
        django_get_or_create = ("is_default",)

    name = "Alimentation Maisha"
    address = "12 avenue Kasa-Vubu, Goma"
    phone = "+243 990 000 000"
    email = "contact@maishanimungu.com"
    tax_number = "A1234567B"
    invoice_footer = "Paiement à 30 jours."
    is_default = True


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@maishanimungu.com")
    full_name = factory.Sequence(lambda n: f"Utilisateur {n}")
    role = User.Role.CASHIER
    is_active = True

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        obj.set_password(extracted or "motdepasse-de-test")
        obj.save()


class OwnerFactory(UserFactory):
    role = User.Role.OWNER
    is_staff = True


class ManagerFactory(UserFactory):
    role = User.Role.MANAGER


class CashierFactory(UserFactory):
    role = User.Role.CASHIER
