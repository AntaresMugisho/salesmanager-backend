import re

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article, Category, Supplier
from apps.stock.status import derive_stock_status

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
        # Was a hand-inlined copy of the rule, under a comment saying so. It
        # is pure Python over two integers the annotation already provides, so
        # there was never a reason for it to exist separately.
        return derive_stock_status(obj.stock_quantity, obj.stock_threshold)


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
    # Not Article columns. `initial_quantity` posts an opening movement on
    # create and is ignored on update; `reorder_threshold` lives on StockLevel.
    initial_quantity = serializers.IntegerField(
        min_value=0, write_only=True, required=False, default=0
    )
    reorder_threshold = serializers.IntegerField(
        min_value=0, write_only=True, required=False
    )
    barcode = serializers.CharField(
        max_length=13, required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    vat_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )

    BARCODE_PATTERN = re.compile(r"^\d{8}$|^\d{13}$")

    class Meta:
        model = Article
        fields = [
            "id",
            "sku",
            "barcode",
            "name",
            "description",
            "initial_quantity",
            "reorder_threshold",
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
        # `sku` stays in `fields` — that is what keeps it in every response.
        # It is allocated by Article.save(); a client can never send one.
        read_only_fields = ["id", "sku", "image_url", "created_at", "updated_at"]

    def get_stock(self, obj):
        return StockSummarySerializer(obj, context=self.context).data

    def validate_barcode(self, value):
        if not value or not value.strip():
            return None
        barcode = value.strip()
        if not self.BARCODE_PATTERN.match(barcode):
            raise serializers.ValidationError(
                _("Le code-barres doit contenir 8 ou 13 chiffres.")
            )
        existing = Article.objects.filter(barcode=barcode)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Ce code-barres est déjà utilisé."))
        return barcode

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        return name

    def validate(self, attrs):
        if "description" in attrs:
            value = attrs["description"]
            attrs["description"] = value.strip() or None if value else None

        # Mirrors the frontend's cross-field refine. Resolved against the
        # instance on a PATCH that sends only one of the two.
        purchase = attrs.get(
            "purchase_price",
            self.instance.purchase_price if self.instance else 0,
        )
        sale = attrs.get("sale_price", self.instance.sale_price if self.instance else 0)
        if sale < purchase:
            raise serializers.ValidationError(
                {
                    "sale_price": [
                        _(
                            "Le prix de vente doit être supérieur ou égal au "
                            "prix d'achat."
                        )
                    ]
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from apps.stock.models import StockLevel, StockMovement

        initial_quantity = validated_data.pop("initial_quantity", 0)
        reorder_threshold = validated_data.pop("reorder_threshold", 0)

        site = self.context["site"]
        article = Article.objects.create(**validated_data)
        StockLevel.objects.create(
            article=article,
            site=site,
            quantity=initial_quantity,
            reorder_threshold=reorder_threshold,
        )

        # The article, its level and its opening movement are written
        # together: a level without a matching ledger entry is a stock figure
        # nothing accounts for.
        if initial_quantity > 0:
            user = self.context["request"].user
            StockMovement.objects.create(
                article=article,
                site=site,
                type="IN",
                reason="PURCHASE",
                quantity=initial_quantity,
                quantity_before=0,
                quantity_after=initial_quantity,
                unit_cost=article.purchase_price,
                note="Stock initial",
                user=user,
                user_name=user.full_name,
            )
        return article

    @transaction.atomic
    def update(self, instance, validated_data):
        from apps.stock.models import StockLevel

        # Silently dropped, not rejected: `ArticleUpdateDto` omits it by
        # design, so a client sending it is sending a field that does not
        # exist rather than making an error worth reporting.
        validated_data.pop("initial_quantity", None)
        reorder_threshold = validated_data.pop("reorder_threshold", None)

        article = super().update(instance, validated_data)

        if reorder_threshold is not None:
            # `update_or_create`, not `filter().update()`: an article seeded
            # outside the API has no level row, and filtering for one that was
            # never written matches nothing, updates nothing, and still answers
            # 200 — a write that reports success and does not happen.
            #
            # Only the threshold is passed as a default. Quantity keeps its
            # model default of 0 on the row this creates and is untouched on
            # one that already exists, because quantity has exactly one writer.
            StockLevel.objects.update_or_create(
                article=article,
                site=self.context["site"],
                defaults={"reorder_threshold": reorder_threshold},
            )
        return article
