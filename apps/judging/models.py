"""
judging -- models

Implements FR modules: JUDGE
Depends on: submissions, hackathons

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Per Design Spec Sec 3.3: every tenant-scoped model must use
TenantScopedManager from apps.core and declare its scoping field.
See Document 05 (Database Design) for the real fields/tables to implement.
"""

from django.db import models

# from apps.core.models import TimeStampedModel
# from apps.core.managers import TenantScopedManager

# class Example(TimeStampedModel):
#     organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
#
#     class Meta:
#         app_label = "judging"
