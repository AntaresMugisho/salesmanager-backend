"""Validation of references a device minted for itself while offline.

The server allocates `FA-YYYY-NNNN` under a row lock. A device offline cannot
reach that lock, so it numbers documents in a series of its own,
`FA-C2-YYYY-NNNN`, which no other device and no server allocation can collide
with. Nothing here allocates: by the time a reference reaches this module it
is already printed on a customer's receipt. This only checks that a device is
writing where it is entitled to write.
"""

import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

#: `FA-C2-2026-0007`. Anchored, and the number is exactly four digits: the
#: device pads its counter the same way `next_reference` does, so a reference
#: that does not match was not minted by our client.
DEVICE_REFERENCE = re.compile(r"^(?P<prefix>[A-Z]{2})-(?P<code>C\d+)-\d{4}-\d{4}$")


def validate_device_reference(
    reference: str,
    *,
    prefix: str,
    device_code: str,
    field: str = "reference",
) -> str:
    """Return `reference` if this device may write it, else raise.

    Two ways to fail, kept separate because they mean different things: a
    malformed reference is a client bug, while a well-formed reference in
    another device's series is a client writing outside its own numbering —
    the one thing that could produce a duplicate number on two receipts.
    """
    match = DEVICE_REFERENCE.match(reference or "")

    if not match or match.group("prefix") != prefix:
        raise serializers.ValidationError(
            {field: [_("Référence invalide pour un document hors ligne.")]}
        )

    if match.group("code") != device_code:
        raise serializers.ValidationError(
            {
                field: [
                    _(
                        "La référence « %(reference)s » n'appartient pas à la "
                        "série de cet appareil."
                    )
                    % {"reference": reference}
                ]
            }
        )

    return reference


def resolve_offline_write(request):
    """Return `(device, client_uuid)` for a write replayed from a queue.

    `(None, None)` for an ordinary online write, which is every request that
    sends no `X-Device-Code`. A device code that names no registered device is
    an error rather than a silent fall-back to the online path: falling back
    would allocate a server reference for a sale whose receipt is already
    printed with a different number.
    """
    # Imported here rather than at module scope: `apps.common` is imported by
    # every app, and a top-level import of `apps.accounts` would make the
    # dependency circular.
    from apps.accounts.models import Device

    code = request.headers.get("X-Device-Code")
    key = request.headers.get("Idempotency-Key")

    if not code:
        return None, None

    device = Device.objects.filter(code=code).first()
    if device is None:
        raise serializers.ValidationError(
            {"deviceCode": [_("Appareil inconnu. Enregistrez-le à nouveau.")]}
        )

    return device, key or None
