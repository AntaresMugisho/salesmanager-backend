import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.expenses.models import Expense


class ExpenseFactory(DjangoModelFactory):
    class Meta:
        model = Expense

    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    category = Expense.Category.RENT
    label = factory.Sequence(lambda n: f"Charge {n}")
    amount = 50_000
    method = "CASH"
    spent_at = factory.LazyFunction(timezone.now)
    reference = None
    note = None
