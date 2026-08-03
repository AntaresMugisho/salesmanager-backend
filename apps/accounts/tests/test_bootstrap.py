import pytest
from django.core.management import call_command

from apps.accounts.models import Site, User

pytestmark = pytest.mark.django_db

ARGS = dict(
    email="proprio@shop.cd",
    full_name="Olivier Kabila",
    password="un-mot-de-passe-solide",
    site_name="Alimentation Maisha",
    site_address="12 avenue Kasa-Vubu, Goma",
)


def run(**overrides):
    call_command("bootstrap", **{**ARGS, **overrides})


def test_bootstrap_creates_a_site_and_an_owner():
    run()
    site = Site.objects.current()
    assert site.name == "Alimentation Maisha"

    owner = User.objects.get(email="proprio@shop.cd")
    assert owner.role == User.Role.OWNER
    assert owner.is_staff is True
    assert owner.check_password("un-mot-de-passe-solide")


def test_bootstrap_is_idempotent():
    run()
    run(site_name="Ignoré", email="autre@shop.cd")
    assert Site.objects.count() == 1
    assert Site.objects.current().name == "Alimentation Maisha"


def test_bootstrap_does_not_add_a_second_owner_when_one_exists():
    run()
    run(email="autre@shop.cd")
    assert User.objects.filter(role=User.Role.OWNER).count() == 1


def test_bootstrap_creates_the_owner_when_only_the_site_exists():
    Site.objects.create(name="Déjà là", address="quelque part")
    run()
    assert User.objects.filter(role=User.Role.OWNER, is_active=True).count() == 1


def test_bootstrap_rejects_a_weak_password():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        run(password="1234")
