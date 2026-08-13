from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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


class SiteManager(models.Manager):
    def current(self):
        """The single Site row.

        Later sub-projects call this rather than threading a `site_id`
        through their signatures. A `siteId` arriving from the client is
        accepted and ignored — never used to filter — so the frontend needs
        no change today and real multi-site scoping stays a migration rather
        than a rewrite.
        """
        site = self.filter(is_default=True).first() or self.order_by("created_at").first()
        if site is None:
            raise Site.DoesNotExist(_("Aucun établissement n'est configuré."))
        return site


class Site(UUIDModel):
    name = models.CharField(_("nom"), max_length=200)
    address = models.TextField(_("adresse"))
    phone = models.CharField(_("téléphone"), max_length=50, null=True, blank=True)
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=100, null=True, blank=True
    )
    invoice_footer = models.TextField(_("pied de facture"), null=True, blank=True)
    is_default = models.BooleanField(_("établissement par défaut"), default=True)

    objects = SiteManager()

    class Meta:
        verbose_name = _("établissement")
        verbose_name_plural = _("établissements")
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="unique_default_site",
            )
        ]

    def __str__(self):
        return self.name

    def save(self, **kwargs):
        if self._state.adding and Site.objects.exists():
            raise ValidationError(_("Un seul établissement peut exister."))
        super().save(**kwargs)


class Device(UUIDModel):
    """One installation of the app that can record documents offline.

    `install_id` is minted on the device and is what makes registration
    idempotent — a device that reinstalls the app gets its existing code back
    rather than a second one. `code` is assigned by the server so it is unique
    by construction, which is what lets every reference the device ever emits
    be unique without any further coordination.
    """

    install_id = models.UUIDField(_("identifiant d'installation"), unique=True)
    code = models.CharField(_("code"), max_length=8, unique=True)
    label = models.CharField(_("libellé"), max_length=60)
    last_seen_at = models.DateTimeField(
        _("vu pour la dernière fois"), null=True, blank=True
    )

    class Meta:
        verbose_name = _("appareil")
        verbose_name_plural = _("appareils")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.label}"
