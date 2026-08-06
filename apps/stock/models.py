from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.catalogue.models import Article
from apps.common.models import UUIDModel


class StockLevel(UUIDModel):
    """The current quantity of one article at one site.

    Written only by `apps.stock.services.apply_movement`, with one exception:
    article creation writes the opening row alongside the article itself, and
    article update may change `reorder_threshold`. Quantity has exactly one
    writer.
    """

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="levels",
        verbose_name=_("article"),
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name="stock_levels"
    )
    quantity = models.PositiveIntegerField(_("quantité"), default=0)
    reorder_threshold = models.PositiveIntegerField(
        _("seuil de réapprovisionnement"), default=0
    )

    class Meta:
        verbose_name = _("niveau de stock")
        verbose_name_plural = _("niveaux de stock")
        constraints = [
            models.UniqueConstraint(
                fields=["article", "site"],
                name="one_stock_level_per_article_and_site",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.article.sku}: {self.quantity}"

    @property
    def status(self) -> str:
        """Mirrors `deriveStatus` in the frontend's `lib/service-utils.ts`.

        Both comparisons are inclusive. `ArticleFilterSet` derives the same
        three buckets in SQL; if you change one, change both, or the
        low-stock list and the article filter start disagreeing.
        """
        if self.quantity <= 0:
            return "OUT_OF_STOCK"
        if self.quantity <= self.reorder_threshold:
            return "LOW"
        return "IN_STOCK"


class StockMovement(UUIDModel):
    """One append-only ledger entry.

    Nothing updates or deletes a movement, in this sub-project or any later
    one. A correction is a new, compensating movement.
    """

    class Type(models.TextChoices):
        IN = "IN", _("Entrée")
        OUT = "OUT", _("Sortie")
        ADJUSTMENT = "ADJUSTMENT", _("Ajustement")

    class Reason(models.TextChoices):
        PURCHASE = "PURCHASE", _("Achat fournisseur")
        SALE = "SALE", _("Vente")
        RETURN = "RETURN", _("Retour")
        DAMAGE = "DAMAGE", _("Casse")
        LOSS = "LOSS", _("Perte")
        COUNT_CORRECTION = "COUNT_CORRECTION", _("Correction d'inventaire")
        OTHER = "OTHER", _("Autre")

    article = models.ForeignKey(
        Article, on_delete=models.PROTECT, related_name="movements"
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="movements")
    type = models.CharField(_("type"), max_length=16, choices=Type.choices)
    reason = models.CharField(_("motif"), max_length=20, choices=Reason.choices)
    # Always positive; `type` carries the direction. For an ADJUSTMENT this is
    # the delta that was applied, not the counted target the client sent.
    quantity = models.PositiveIntegerField(_("quantité"))
    quantity_before = models.PositiveIntegerField(_("quantité avant"))
    quantity_after = models.PositiveIntegerField(_("quantité après"))
    unit_cost = models.PositiveIntegerField(_("coût unitaire"), null=True, blank=True)
    reference = models.CharField(_("référence"), max_length=40, null=True, blank=True)
    note = models.CharField(_("note"), max_length=300, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements"
    )
    # Denormalised so the ledger still reads correctly after a rename, and so
    # the reports sub-project can print `userName` on a document without a join.
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        # `-id` is a tiebreaker: two movements created in the same transaction
        # can share a timestamp to the microsecond on SQLite, and an unstable
        # sort makes pagination drop or repeat rows.
        ordering = ["-created_at", "-id"]
        verbose_name = _("mouvement de stock")
        verbose_name_plural = _("mouvements de stock")

    def __str__(self) -> str:
        return f"{self.type} {self.quantity} × {self.article.sku}"
