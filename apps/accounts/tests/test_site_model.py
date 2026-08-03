import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import Site

pytestmark = pytest.mark.django_db


def make_site(**overrides):
    values = {"name": "Alimentation Maisha", "address": "12 av. Kasa-Vubu, Goma"}
    values.update(overrides)
    return Site.objects.create(**values)


def test_current_returns_the_only_site():
    site = make_site()
    assert Site.objects.current() == site


def test_current_raises_when_unconfigured():
    """An unconfigured deployment is a server misconfiguration, and
    `manage.py bootstrap` is the fix."""
    with pytest.raises(Site.DoesNotExist):
        Site.objects.current()


def test_a_second_site_is_refused_by_the_save_guard():
    make_site()
    with pytest.raises(ValidationError):
        make_site(name="Deuxième")


def test_a_second_site_is_refused_by_the_database_too():
    """The partial unique index is the real constraint; the save guard only
    makes the failure comprehensible."""
    make_site()
    with pytest.raises(IntegrityError), transaction.atomic():
        Site.objects.bulk_create(
            [Site(name="Deuxième", address="ailleurs", is_default=True)]
        )


def test_optional_fields_default_to_null_not_blank():
    """The frontend's type promises `string | null`."""
    site = make_site()
    assert site.phone is None
    assert site.email is None
    assert site.tax_number is None
    assert site.invoice_footer is None


def test_updating_the_existing_site_is_allowed():
    site = make_site()
    site.name = "Alimentation Maisha SARL"
    site.save()
    site.refresh_from_db()
    assert site.name == "Alimentation Maisha SARL"


def test_id_is_a_uuid():
    from uuid import UUID

    assert isinstance(make_site().id, UUID)
