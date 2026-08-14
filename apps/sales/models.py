from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.catalogue.models import Article
from apps.common.models import UUIDModel


class Customer(UUIDModel):
    """Structurally a Supplier plus a tax number.

    `is_active` exists so an archived customer stops appearing in the sale
    form's picker. There is deliberately no `?isActive=` list filter: the
    contract's `listCustomers` takes SimpleListParams — search only.
    """

    name = models.CharField(_("nom"), max_length=80)
    contact_name = models.CharField(
        _("nom du contact"), max_length=80, null=True, blank=True
    )
    email = models.EmailField(_("adresse e-mail"), null=True, blank=True)
    phone = models.CharField(_("téléphone"), max_length=20, null=True, blank=True)
    address = models.CharField(_("adresse"), max_length=200, null=True, blank=True)
    tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=30, null=True, blank=True
    )
    notes = models.CharField(_("notes"), max_length=500, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("client")
        verbose_name_plural = _("clients")
        constraints = [
            models.UniqueConstraint(Lower("name"), name="customer_name_unique_ci"),
        ]

    def __str__(self) -> str:
        return self.name


class Sale(UUIDModel):
    """The sale *is* the invoice — `reference` is its FA-YYYY-NNNN number.

    Immutable apart from cancellation. `paidAmount`, `balance` and
    `paymentStatus` are computed on every read and are deliberately not
    columns: a stored status can disagree with the payments it summarises.
    """

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", _("Finalisée")
        CANCELLED = "CANCELLED", _("Annulée")

    reference = models.CharField(_("référence"), max_length=20, unique=True)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="sales",
        null=True,
        blank=True,
        verbose_name=_("client"),
    )
    # Snapshotted, not resolved at read time. The frontend resolves live and
    # argues it is safe because deletion is blocked — true for deletion, but a
    # rename or a move would rewrite every historical invoice.
    customer_name = models.CharField(_("client"), max_length=80, null=True, blank=True)
    customer_address = models.CharField(
        _("adresse"), max_length=200, null=True, blank=True
    )
    customer_tax_number = models.CharField(
        _("numéro d'identification fiscale"), max_length=30, null=True, blank=True
    )
    status = models.CharField(
        _("statut"), max_length=16, choices=Status.choices, default=Status.COMPLETED
    )
    subtotal = models.PositiveIntegerField(_("sous-total"), default=0)
    discount = models.PositiveIntegerField(_("remise"), default=0)
    # How the discount was entered, so the UI can redisplay "10 %" rather than
    # "1 500 FC". Never used in arithmetic — `discount` is authoritative.
    discount_rate = models.DecimalField(
        _("taux de remise"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    total = models.PositiveIntegerField(_("total"), default=0)
    # Included in `total`, never added to it.
    vat_total = models.PositiveIntegerField(_("TVA"), default=0)
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    cancelled_at = models.DateTimeField(_("annulée le"), null=True, blank=True)
    cancel_reason = models.CharField(
        _("motif d'annulation"), max_length=300, null=True, blank=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("vente")
        verbose_name_plural = _("ventes")

    def __str__(self) -> str:
        return self.reference


class SaleLine(UUIDModel):
    """One line of a sale, with everything about the article frozen.

    Nothing here is resolved back to the article afterwards: repricing an
    article must not rewrite an existing sale.
    """

    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="lines", verbose_name=_("vente")
    )
    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="sale_lines"
    )
    article_name = models.CharField(_("article"), max_length=120)
    article_sku = models.CharField(_("référence"), max_length=32)
    unit = models.CharField(_("unité"), max_length=8, choices=Article.Unit.choices)
    quantity = models.PositiveIntegerField(_("quantité"))
    # TTC. Defaults to the article's sale price, but may be negotiated down.
    unit_price = models.PositiveIntegerField(_("prix unitaire"))
    # The article's purchase price at sale time. Sub-project 6 computes COGS
    # and margin from this and never re-joins to the article.
    unit_cost = models.PositiveIntegerField(_("coût unitaire"))
    vat_rate = models.DecimalField(_("taux de TVA"), max_digits=5, decimal_places=2)
    line_total = models.PositiveIntegerField(_("total ligne"))
    discount_share = models.PositiveIntegerField(_("part de remise"), default=0)
    vat_amount = models.PositiveIntegerField(_("TVA"), default=0)

    class Meta:
        verbose_name = _("ligne de vente")
        verbose_name_plural = _("lignes de vente")

    def __str__(self) -> str:
        return f"{self.article_sku} × {self.quantity}"


class Payment(UUIDModel):
    """Append-only: nothing updates or deletes a payment."""

    class Method(models.TextChoices):
        CASH = "CASH", _("Espèces")
        MOBILE_MONEY = "MOBILE_MONEY", _("Mobile money")
        BANK_TRANSFER = "BANK_TRANSFER", _("Virement bancaire")
        CARD = "CARD", _("Carte")
        OTHER = "OTHER", _("Autre")

    sale = models.ForeignKey(
        Sale, on_delete=models.PROTECT, related_name="payments", verbose_name=_("vente")
    )
    amount = models.PositiveIntegerField(_("montant"))
    method = models.CharField(_("moyen"), max_length=20, choices=Method.choices)
    paid_at = models.DateTimeField(_("payé le"))
    reference = models.CharField(_("référence"), max_length=40, null=True, blank=True)
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["paid_at", "id"]
        verbose_name = _("paiement")
        verbose_name_plural = _("paiements")

    def __str__(self) -> str:
        return f"{self.amount} — {self.sale.reference}"
