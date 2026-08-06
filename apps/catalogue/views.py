from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from apps.catalogue.models import Category, Supplier
from apps.catalogue.serializers import CategorySerializer, SupplierSerializer
from apps.common.exceptions import Conflict
from apps.common.views import CatalogueViewSet


class CategoryViewSet(CatalogueViewSet):
    serializer_class = CategorySerializer
    search_fields = ["name", "description"]
    ordering_fields = ["name", "article_count"]
    ordering = ["name"]

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
    ordering = ["name"]

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
        instance.delete()
