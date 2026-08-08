from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.common.models import UUIDModel
from apps.sales.models import Payment


class Expense(UUIDModel):
    """Money leaving the shop that is not a stock purchase.

    Editable and deletable, unlike a sale: nothing references an expense, and
    it is a private record rather than a document issued to anyone.
    """

    class Category(models.TextChoices):
        RENT = "RENT", _("Loyer")
        SALARY = "SALARY", _("Salaires")
        UTILITIES = "UTILITIES", _("Eau et électricité")
        TRANSPORT = "TRANSPORT", _("Transport")
        SUPPLIES = "SUPPLIES", _("Fournitures")
        TAX = "TAX", _("Taxes et impôts")
        OTHER = "OTHER", _("Autre")

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="expenses")
    category = models.CharField(_("catégorie"), max_length=16, choices=Category.choices)
    label = models.CharField(_("libellé"), max_length=120)
    amount = models.PositiveIntegerField(_("montant"))
    # Reused, not redeclared: an expense is paid the same five ways a sale is.
    method = models.CharField(_("moyen"), max_length=20, choices=Payment.Method.choices)
    spent_at = models.DateTimeField(_("dépensé le"))
    reference = models.CharField(_("référence"), max_length=40, null=True, blank=True)
    note = models.CharField(_("note"), max_length=500, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses"
    )
    user_name = models.CharField(_("auteur"), max_length=150)

    class Meta:
        ordering = ["-spent_at", "-id"]
        verbose_name = _("charge")
        verbose_name_plural = _("charges")

    def __str__(self) -> str:
        return f"{self.label} — {self.amount}"
