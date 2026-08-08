from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Site
from apps.catalogue.filters import ArticleFilterSet
from apps.catalogue.models import Category, Supplier
from apps.catalogue.querysets import article_queryset
from apps.catalogue.serializers import (
    ArticleSerializer,
    CategorySerializer,
    SupplierSerializer,
)
from apps.common.exceptions import Conflict
from apps.common.views import CatalogueViewSet


class CategoryViewSet(CatalogueViewSet):
    serializer_class = CategorySerializer
    search_fields = ["name", "description"]
    ordering_fields = ["name", "article_count"]
    # `ordering` must name the column directly: DRF resolves aliases only on
    # the ?ordering= path, and returns the default untouched otherwise.
    ordering_aliases = {"name": "name_sort"}
    ordering = ["name_sort"]

    def get_queryset(self):
        # Annotated rather than counted per row: a page of 20 categories would
        # otherwise issue 20 extra queries.
        return Category.objects.annotate(article_count=Count("articles"))

    def perform_create(self, serializer):
        # Re-read through the annotated queryset. `create()` returns a bare
        # Category, which has no `article_count` attribute, so the response
        # would omit the key the frontend's type requires.
        instance = serializer.save()
        serializer.instance = self.get_queryset().get(pk=instance.pk)

    def perform_destroy(self, instance):
        used = instance.articles.count()
        if used:
            raise Conflict(
                _(
                    "Cette catégorie contient %(count)d article%(plural)s "
                    "et ne peut pas être supprimée."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()


class SupplierViewSet(CatalogueViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    search_fields = ["name", "contact_name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    ordering_aliases = {"name": "name_sort"}
    ordering = ["name_sort"]

    def perform_destroy(self, instance):
        used = instance.articles.count()
        if used:
            raise Conflict(
                _(
                    "Ce fournisseur est lié à %(count)d article%(plural)s "
                    "et ne peut pas être supprimé."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )

        # StockTransaction.supplier is PROTECT, so without this the delete
        # raises ProtectedError and the envelope renders a 500.
        transactions = instance.transactions.count()
        if transactions:
            raise Conflict(
                _(
                    "Ce fournisseur est lié à %(count)d transaction%(plural)s "
                    "et ne peut pas être supprimé."
                )
                % {"count": transactions, "plural": "s" if transactions > 1 else ""}
            )

        instance.delete()


class ArticleViewSet(CatalogueViewSet):
    serializer_class = ArticleSerializer
    filterset_class = ArticleFilterSet
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "sku", "created_at", "sale_price"]
    ordering_aliases = {"stock": "stock_quantity", "name": "name_sort"}
    ordering = ["name_sort"]

    @property
    def site(self):
        # Resolved once per request. The queryset and the serializer context
        # both need it, and Site.objects.current() is a query each time.
        if not hasattr(self, "_site"):
            self._site = Site.objects.current()
        return self._site

    def get_queryset(self):
        return article_queryset(site=self.site)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["site"] = self.site
        return context

    def perform_create(self, serializer):
        # Re-read through the annotated queryset. `create()` returns a bare
        # Article, which has no `stock_quantity` attribute, and the response
        # serializer's `stock` field would raise AttributeError on it.
        instance = serializer.save()
        serializer.instance = self.get_queryset().get(pk=instance.pk)

    def perform_update(self, serializer):
        instance = serializer.save()
        serializer.instance = self.get_queryset().get(pk=instance.pk)

    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise Conflict(
                _(
                    "Cet article possède un historique de mouvements et ne "
                    "peut pas être supprimé. Vous pouvez l'archiver."
                )
            )
        instance.delete()
