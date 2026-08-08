from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.common.models import NameSortedModel, UUIDModel

#: `name_sort` is twice its source field: ligature expansion lengthens the key,
#: so a name at the limit would overflow a column of equal width.
NAME_SORT_FACTOR = 2


class Category(NameSortedModel, UUIDModel):
    name = models.CharField(_("nom"), max_length=60)
    # Never serialized — an ordering key, not part of the API contract.
    name_sort = models.CharField(
        max_length=60 * NAME_SORT_FACTOR, editable=False, db_index=True, default=""
    )
    description = models.CharField(
        _("description"), max_length=200, null=True, blank=True
    )

    class Meta:
        ordering = ["name_sort"]
        verbose_name = _("catégorie")
        verbose_name_plural = _("catégories")
        constraints = [
            # A functional index, not `unique=True`: the frontend compares
            # names with `toLocaleLowerCase("fr-FR")`, so "Boissons" and
            # "BOISSONS" are the same category to a user. The serializer
            # produces the French message; this is what holds under a race.
            models.UniqueConstraint(Lower("name"), name="category_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Supplier(NameSortedModel, UUIDModel):
    name = models.CharField(_("nom"), max_length=80)
    name_sort = models.CharField(
        max_length=80 * NAME_SORT_FACTOR, editable=False, db_index=True, default=""
    )
    contact_name = models.CharField(
        _("nom du contact"), max_length=80, null=True, blank=True
    )
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    phone = models.CharField(_("téléphone"), max_length=20, null=True, blank=True)
    address = models.CharField(_("adresse"), max_length=200, null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name_sort"]
        verbose_name = _("fournisseur")
        verbose_name_plural = _("fournisseurs")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="supplier_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Article(NameSortedModel, UUIDModel):
    class Unit(models.TextChoices):
        PIECE = "PIECE", _("Pièce")
        KG = "KG", _("Kilogramme")
        LITRE = "LITRE", _("Litre")
        PAQUET = "PAQUET", _("Paquet")
        CARTON = "CARTON", _("Carton")

    sku = models.CharField(_("référence"), max_length=32)
    # NULL rather than "" — the column is unique, and "" collides with itself,
    # so a second barcode-less article would be rejected.
    barcode = models.CharField(_("code-barres"), max_length=13, null=True, blank=True)
    name = models.CharField(_("nom"), max_length=120)
    name_sort = models.CharField(
        max_length=120 * NAME_SORT_FACTOR, editable=False, db_index=True, default=""
    )
    description = models.CharField(
        _("description"), max_length=500, null=True, blank=True
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("catégorie"),
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="articles",
        null=True,
        blank=True,
        verbose_name=_("fournisseur"),
    )
    unit = models.CharField(
        _("unité"), max_length=8, choices=Unit.choices, default=Unit.PIECE
    )
    # Cents. The frontend's `Cents` type is an integer and every price input
    # is `.int()`; storing a float here would reintroduce rounding error into
    # figures the reports sub-project has to reconcile exactly.
    purchase_price = models.PositiveIntegerField(_("prix d'achat"), default=0)
    sale_price = models.PositiveIntegerField(_("prix de vente"), default=0)
    # The only decimal in this sub-project: the article form normalises a
    # decimal comma, so "5,5" is a rate a user can enter.
    vat_rate = models.DecimalField(
        _("taux de TVA"), max_digits=5, decimal_places=2, default=0
    )
    is_active = models.BooleanField(_("actif"), default=True)
    image_url = models.URLField(_("image"), null=True, blank=True)

    class Meta:
        ordering = ["name_sort"]
        verbose_name = _("article")
        verbose_name_plural = _("articles")
        constraints = [
            models.UniqueConstraint(Lower("sku"), name="article_sku_unique_ci"),
            models.UniqueConstraint(
                "barcode",
                name="article_barcode_unique",
                condition=models.Q(barcode__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"
