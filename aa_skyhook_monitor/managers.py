"""Managers"""

from django.db import models
from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone


class SkyhookQuerySet(models.QuerySet):
    def with_reagents(self):
        return self.filter(reagents__isnull=False).distinct()

    def ordered_by_vuln(self):
        now = timezone.now()
        return self.annotate(
            vuln_order=Case(
                When(
                    theft_vulnerability_start__lte=now,
                    theft_vulnerability_end__gte=now,
                    then=Value(0),
                ),
                When(theft_vulnerability_start__gt=now, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("vuln_order", F("theft_vulnerability_start").asc(nulls_last=True))


class SkyhookManager(models.Manager):
    def get_queryset(self) -> SkyhookQuerySet:
        return SkyhookQuerySet(self.model, using=self._db)

    def with_reagents(self):
        return self.get_queryset().with_reagents()
