import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement


class StockLevelFactory(DjangoModelFactory):
    class Meta:
        model = StockLevel

    article = factory.SubFactory(ArticleFactory)
    site = factory.SubFactory(SiteFactory)
    quantity = 0
    reorder_threshold = 0


class StockMovementFactory(DjangoModelFactory):
    class Meta:
        model = StockMovement

    article = factory.SubFactory(ArticleFactory)
    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    type = StockMovement.Type.IN
    reason = StockMovement.Reason.PURCHASE
    quantity = 10
    quantity_before = 0
    quantity_after = 10
    unit_cost = 1000
    reference = None
    note = None
