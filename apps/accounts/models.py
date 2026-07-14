"""
accounts -- models

Implements FR modules: AUTH, PROFILE
Depends on: core

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Per Design Spec Sec 3.3: every tenant-scoped model must use
TenantScopedManager from apps.core and declare its scoping field.
See Document 05 (Database Design) for the real fields/tables to implement.
"""


# from apps.core.models import TimeStampedModel
# from apps.core.managers import TenantScopedManager

# class Example(TimeStampedModel):
#     organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
#
#     class Meta:
#         app_label = "accounts"

from django.contrib.auth.models import AbstractUser
from django.db import models


class Account(AbstractUser):
    """
    Custom user model.
    Extend later with profile fields.
    """

    pass