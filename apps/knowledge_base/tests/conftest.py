import pytest
from rest_framework.test import APIClient
from apps.accounts.tests.factories import AccountFactory
from .factories import CategoryFactory, ArticleFactory, PublishedArticleFactory, FAQFactory, PublishedFAQFactory

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def platform_admin():
    return AccountFactory(is_platform_admin=True)

@pytest.fixture
def regular_user():
    return AccountFactory(is_platform_admin=False)

@pytest.fixture
def auth_headers(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)
    return {}

@pytest.fixture
def admin_headers(api_client, platform_admin):
    api_client.force_authenticate(user=platform_admin)
    return {}

@pytest.fixture
def category():
    return CategoryFactory()

@pytest.fixture
def published_article(category):
    return PublishedArticleFactory(category=category)

@pytest.fixture
def faq_factory():
    return FAQFactory

@pytest.fixture
def published_faq_factory():
    return PublishedFAQFactory

