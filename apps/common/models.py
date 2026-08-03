from uuid import uuid4

from django.db import models


class UUIDModel(models.Model):
    """Base for every domain model in every sub-project.

    UUID primary keys because the frontend's `UUID` type says so, and because
    they let the frontend mint optimistic ids if it ever needs to.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
