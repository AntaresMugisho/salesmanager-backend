import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_email_is_the_username_field():
    assert User.USERNAME_FIELD == "email"
    assert "full_name" in User.REQUIRED_FIELDS


def test_create_user_hashes_the_password():
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "s3cret-pw")
    assert user.password != "s3cret-pw"
    assert user.check_password("s3cret-pw")


def test_new_users_default_to_cashier():
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw")
    assert user.role == User.Role.CASHIER
    assert user.is_active is True
    assert user.is_staff is False


def test_create_superuser_is_always_an_owner():
    user = User.objects.create_superuser("o@shop.cd", "Olivier Kabila", "pw")
    assert user.role == User.Role.OWNER
    assert user.is_staff is True
    assert user.is_superuser is True


def test_email_is_stored_lowercase():
    user = User.objects.create_user("Alice@Shop.CD", "Alice Nkusi", "pw")
    assert user.email == "alice@shop.cd"


def test_email_lookup_is_case_insensitive():
    User.objects.create_user("alice@shop.cd", "Alice Nkusi", "pw")
    assert User.objects.get_by_natural_key("ALICE@SHOP.CD") is not None


def test_duplicate_email_differing_only_in_case_is_rejected():
    """Normalisation at save time is what enforces this on SQLite."""
    from django.db.utils import IntegrityError

    User.objects.create_user("alice@shop.cd", "Alice Nkusi", "pw")
    with pytest.raises(IntegrityError):
        User.objects.create_user("ALICE@SHOP.CD", "Alice Bis", "pw")


def test_create_user_requires_an_email():
    with pytest.raises(ValueError):
        User.objects.create_user("", "Alice Nkusi", "pw")


def test_create_user_requires_a_full_name():
    with pytest.raises(ValueError):
        User.objects.create_user("a@shop.cd", "", "pw")


def test_id_is_a_uuid():
    from uuid import UUID

    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw")
    assert isinstance(user.id, UUID)


@pytest.mark.parametrize(
    ("role", "owner", "manager_or_above"),
    [
        ("OWNER", True, True),
        ("MANAGER", False, True),
        ("CASHIER", False, False),
    ],
)
def test_role_helpers(role, owner, manager_or_above):
    user = User.objects.create_user("a@shop.cd", "Alice Nkusi", "pw", role=role)
    assert user.is_owner is owner
    assert user.is_manager_or_above is manager_or_above


def test_role_labels_are_french():
    assert str(User.Role.OWNER.label) == "Propriétaire"
    assert str(User.Role.MANAGER.label) == "Gérant"
    assert str(User.Role.CASHIER.label) == "Caissier"
