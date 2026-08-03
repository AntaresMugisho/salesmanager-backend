from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, full_name, password, **extra):
        if not email:
            raise ValueError(_("Une adresse e-mail est obligatoire."))
        if not full_name:
            raise ValueError(_("Un nom complet est obligatoire."))
        user = self.model(
            email=self.normalize_email(email).lower(),
            full_name=full_name,
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, full_name, password=None, **extra):
        extra.setdefault("role", User.Role.CASHIER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, full_name, password, **extra)

    def create_superuser(self, email, full_name, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        extra["role"] = User.Role.OWNER
        return self._create_user(email, full_name, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Replaces django.contrib.auth.User.

    Set as AUTH_USER_MODEL in sub-project 1 because swapping it once other
    apps hold foreign keys to it is a rewrite, not a migration.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", _("Propriétaire")
        MANAGER = "MANAGER", _("Gérant")
        CASHIER = "CASHIER", _("Caissier")

    email = models.EmailField(_("adresse e-mail"), unique=True)
    full_name = models.CharField(_("nom complet"), max_length=150)
    role = models.CharField(
        _("rôle"), max_length=16, choices=Role.choices, default=Role.CASHIER
    )
    avatar_url = models.URLField(_("avatar"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)
    is_staff = models.BooleanField(_("accès à l'administration"), default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def save(self, **kwargs):
        # Django 6 removed positional arguments to Model.save().
        #
        # Lowercasing here is what enforces case-insensitive uniqueness: the
        # unique index is on the stored value, and SQLite has no reliable
        # functional index. A Postgres migration should add one and demote
        # this to belt-and-braces.
        self.email = self.email.strip().lower()
        super().save(**kwargs)

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def is_manager_or_above(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.MANAGER}
