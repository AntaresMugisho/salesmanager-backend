import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article, Category, Supplier

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


class CategorySerializer(serializers.ModelSerializer):
    """The frontend's `Category`.

    `articleCount` is annotated by the queryset, never stored — see
    `CategoryViewSet.get_queryset`.
    """

    description = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    article_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "description", "article_count"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 60:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 60 caractères.")
            )
        # Case-insensitive, matching the frontend's
        # `toLocaleLowerCase("fr-FR")` comparison. A functional unique index
        # backs this up under a race; this is what produces the message.
        existing = Category.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Une catégorie porte déjà ce nom."))
        return name

    def validate(self, attrs):
        if "description" in attrs:
            value = attrs["description"]
            attrs["description"] = value.strip() or None if value else None
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    """The frontend's `Supplier`. Validation mirrors
    `features/suppliers/schema.ts`."""

    contact_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = ("contact_name", "email", "phone", "address", "notes")

    class Meta:
        model = Supplier
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 80:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 80 caractères.")
            )
        existing = Supplier.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un fournisseur porte déjà ce nom."))
        return name

    def validate_phone(self, value):
        if not value or not value.strip():
            return value
        if not PHONE_PATTERN.match(value.strip()):
            raise serializers.ValidationError(_("Numéro de téléphone invalide."))
        return value

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class SupplierRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name"]


class ArticleRefSerializer(serializers.ModelSerializer):
    """The frontend's `ArticleRef`.

    Lives here rather than in `apps.stock` so the movement serializer can
    import it without closing an import cycle.
    """

    class Meta:
        model = Article
        fields = ["id", "sku", "name", "unit"]


class StockSummarySerializer(serializers.Serializer):
    """The frontend's `StockSummary`, built from the queryset annotations
    rather than from the related StockLevel row."""

    site_id = serializers.SerializerMethodField()
    quantity = serializers.IntegerField(source="stock_quantity", read_only=True)
    reorder_threshold = serializers.IntegerField(
        source="stock_threshold", read_only=True
    )
    status = serializers.SerializerMethodField()

    def get_site_id(self, obj) -> str:
        return str(self.context["site"].id)

    def get_status(self, obj) -> str:
        # The same three inclusive comparisons as StockLevel.status and as
        # ArticleFilterSet's SQL. Three copies is two too many; they are kept
        # in step by the tests, which assert the same boundaries in each.
        if obj.stock_quantity <= 0:
            return "OUT_OF_STOCK"
        if obj.stock_quantity <= obj.stock_threshold:
            return "LOW"
        return "IN_STOCK"


class ArticleSerializer(serializers.ModelSerializer):
    """The frontend's `Article`."""

    category = CategoryRefSerializer(read_only=True)
    supplier = SupplierRefSerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=Category.objects.all()
    )
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.all(),
        allow_null=True,
        required=False,
    )
    stock = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id",
            "sku",
            "barcode",
            "name",
            "description",
            "category_id",
            "category",
            "supplier_id",
            "supplier",
            "unit",
            "purchase_price",
            "sale_price",
            "vat_rate",
            "is_active",
            "image_url",
            "stock",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "image_url", "created_at", "updated_at"]

    def get_stock(self, obj):
        return StockSummarySerializer(obj, context=self.context).data
