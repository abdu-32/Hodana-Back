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


import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import TimeStampedModel


class AccountManager(BaseUserManager):
    """Required because Account is a custom AUTH_USER_MODEL (Design Spec Sec 4.1)."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Account requires an email address")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_platform_admin", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("verification_status", "verified")
        return self.create_user(email, password, **extra_fields)


OAUTH_PROVIDER_CHOICES = [("github", "GitHub"), ("google", "Google")]
VERIFICATION_STATUS_CHOICES = [
    ("unverified", "Unverified"),
    ("pending", "Pending"),
    ("verified", "Verified"),
]
PROFILE_VISIBILITY_CHOICES = [
    ("public", "Public"),
    ("private", "Private"),
]


class Account(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Implements FR-AUTH-001..004, FR-PROFILE-001..003 (Design Spec Sec 4.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    bio = models.TextField(blank=True)
    university = models.TextField(blank=True)
    skills = ArrayField(models.TextField(), default=list, blank=True)
    avatar_url = models.TextField(blank=True)  # object storage pointer, Sec 6.3
    portfolio_url = models.TextField(blank=True)
    contact_email = models.EmailField(null=True, blank=True)  # falls back to `email` if unset
    profile_visibility = models.CharField(
        max_length=10, choices=PROFILE_VISIBILITY_CHOICES, default="public"
    )  # FR-PROFILE-002; not in Doc 05/04 yet -- added to make the FR enforceable

    # FR-HACK-003 (age_restriction / geographic_restriction) + FR-ANALYTICS-002
    # (age-bucketed demographics). Both self-reported by the account holder
    # via FR-PROFILE-001 (update_profile), same trust level as `university`
    # -- there's no ID-document verification step for either field, only
    # basic sanity-range validation (see accounts/services.py). Nullable:
    # a hackathon with no age/geographic restriction never requires them,
    # and existing accounts predate these fields.
    date_of_birth = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, null=True, blank=True)  # ISO 3166-1 alpha-2, e.g. "ET"

    oauth_provider = models.CharField(
        max_length=20, choices=OAUTH_PROVIDER_CHOICES, null=True, blank=True
    )
    oauth_subject = models.TextField(null=True, blank=True)

    verification_status = models.CharField(
        max_length=20, choices=VERIFICATION_STATUS_CHOICES, default="unverified"
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)

    is_platform_admin = models.BooleanField(default=False)  # Design Spec Sec 4.3
    token_version = models.IntegerField(default=0)  # FR-AUTH-004, NFR-SEC-005

    failed_login_count = models.SmallIntegerField(default=0)
    lock_until = models.DateTimeField(null=True, blank=True)
    is_suspended = models.BooleanField(default=False)  # FR-ADMIN-001

    last_login_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)  # NFR-COMP-002, Sec 6

    # Django auth plumbing (not in the db doc, but required by AbstractBaseUser)
    is_staff = models.BooleanField(default=False)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        app_label = "accounts"
        indexes = [
            models.Index(
                fields=["lock_until"],
                name="account_lock_until_idx",
                condition=models.Q(lock_until__isnull=False),
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["oauth_provider", "oauth_subject"],
                condition=models.Q(oauth_provider__isnull=False),
                name="unique_oauth_identity",
            ),
        ]

    @property
    def is_active(self):
        return self.deleted_at is None and not self.is_suspended

    def __str__(self):
        return self.email


class Badge(TimeStampedModel):
    TYPE_CHOICES = [
        ("verified_student", "Verified Student"),
        ("hackathon_veteran", "Hackathon Veteran"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="badges")
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    awarded_at = models.DateTimeField()

    class Meta:
        app_label = "accounts"
        indexes = [models.Index(fields=["user"])]


class RoleAssignment(models.Model):
    """Scoped RBAC rows -- Design Spec Sec 4.3. scope_id is polymorphic;
    referential integrity for it is enforced in services.py, not the DB."""

    ROLE_CHOICES = [
        ("organizer", "Organizer"),
        ("sponsor", "Sponsor"),
        ("judge", "Judge"),
        ("mentor", "Mentor"),
    ]
    SCOPE_TYPE_CHOICES = [
        ("organization", "Organization"),
        ("hackathon", "Hackathon"),
        ("track", "Track"),
    ]


    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    scope_type = models.CharField(max_length=20, choices=SCOPE_TYPE_CHOICES)
    scope_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "scope_type", "scope_id"],
                name="unique_role_assignment",
            ),
        ]
        indexes = [models.Index(fields=["scope_type", "scope_id"])]  # HasScopedRole reverse lookup