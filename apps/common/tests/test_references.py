"""Validation of references minted on a device."""

import pytest
from rest_framework import serializers

from apps.common.references import validate_device_reference


def test_accepts_a_well_formed_reference():
    result = validate_device_reference(
        "FA-C2-2026-0007", prefix="FA", device_code="C2"
    )

    assert result == "FA-C2-2026-0007"


def test_accepts_a_multi_digit_device_code():
    result = validate_device_reference(
        "TR-C12-2026-0001", prefix="TR", device_code="C12"
    )

    assert result == "TR-C12-2026-0001"


@pytest.mark.parametrize(
    "reference",
    [
        "FA-2026-0007",        # the shared server series, not a device one
        "FA-C2-2026-7",        # number not padded to four digits
        "FA-C2-26-0007",       # two-digit year
        "fa-c2-2026-0007",     # lowercase
        "FA-C2-2026-0007 ",    # trailing space
        "FA-X2-2026-0007",     # code not of the C<n> shape
        "",
    ],
)
def test_rejects_malformed_references(reference):
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference(reference, prefix="FA", device_code="C2")

    assert "reference" in excinfo.value.detail


def test_rejects_the_wrong_document_prefix():
    with pytest.raises(serializers.ValidationError):
        validate_device_reference("TR-C2-2026-0007", prefix="FA", device_code="C2")


def test_rejects_another_devices_series():
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference("FA-C3-2026-0007", prefix="FA", device_code="C2")

    assert "reference" in excinfo.value.detail


def test_error_is_keyed_on_the_named_field():
    with pytest.raises(serializers.ValidationError) as excinfo:
        validate_device_reference(
            "nonsense", prefix="FA", device_code="C2", field="lines.0.reference"
        )

    assert "lines.0.reference" in excinfo.value.detail
