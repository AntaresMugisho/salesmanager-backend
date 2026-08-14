"""Device registration primitives: code allocation and the model."""

import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Device
from apps.common.sequences import next_device_code

pytestmark = pytest.mark.django_db


def test_codes_are_allocated_in_order():
    with transaction.atomic():
        first = next_device_code()
        second = next_device_code()

    assert first == "C1"
    assert second == "C2"


# `transaction=True` because the ordinary django_db fixture already holds an
# atomic block open, so the guard could never fire. Same reason as
# `apps/common/tests/test_sequences.py`.
@pytest.mark.django_db(transaction=True)
def test_allocation_requires_an_open_transaction():
    with pytest.raises(RuntimeError, match="atomic"):
        next_device_code()


def test_install_id_is_unique():
    install_id = uuid.uuid4()
    Device.objects.create(install_id=install_id, code="C1", label="Caisse 1")

    with pytest.raises(IntegrityError):
        Device.objects.create(install_id=install_id, code="C2", label="Caisse 2")


def test_code_is_unique():
    Device.objects.create(install_id=uuid.uuid4(), code="C1", label="Caisse 1")

    with pytest.raises(IntegrityError):
        Device.objects.create(install_id=uuid.uuid4(), code="C1", label="Caisse 2")


def test_str_is_code_and_label():
    device = Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )

    assert str(device) == "C2 — Caisse principale"
