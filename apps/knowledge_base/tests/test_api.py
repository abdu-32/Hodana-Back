import pytest

def test_get_articles(api_client, published_article):
    response = api_client.get("/api/v1/help/articles/")
    assert response.status_code == 200
    assert "data" in response.data
    assert "meta" in response.data
    assert len(response.data["data"]) == 1

def test_post_articles_unauthorized(api_client, category):
    data = {
        "categoryId": str(category.id),
        "title": "New Article",
        "body": "Body"
    }
    response = api_client.post("/api/v1/help/articles/", data, format="json")
    assert response.status_code == 401

def test_post_articles_forbidden(api_client, auth_headers, category):
    data = {
        "categoryId": str(category.id),
        "title": "New Article",
        "body": "Body"
    }
    response = api_client.post("/api/v1/help/articles/", data, format="json")
    assert response.status_code == 403

def test_post_articles_success(api_client, admin_headers, category):
    data = {
        "categoryId": str(category.id),
        "title": "New Article",
        "body": "Body"
    }
    response = api_client.post("/api/v1/help/articles/", data, format="json")
    assert response.status_code == 201

def test_get_article_detail(api_client, published_article):
    response = api_client.get(f"/api/v1/help/articles/{published_article.slug}/")
    assert response.status_code == 200
    assert response.data["title"] == published_article.title

def test_get_article_detail_draft(api_client, published_article):
    published_article.status = "draft"
    published_article.save()
    response = api_client.get(f"/api/v1/help/articles/{published_article.slug}/")
    assert response.status_code == 404

def test_search_articles(api_client, published_article):
    response = api_client.get(f"/api/v1/help/search/?keyword={published_article.title}")
    assert response.status_code == 200
    assert len(response.data["data"]) == 1

def test_post_feedback_unauthorized(api_client, published_article):
    data = {"isHelpful": True}
    response = api_client.post(f"/api/v1/help/articles/{published_article.slug}/feedback/", data, format="json")
    assert response.status_code == 401

def test_post_feedback_success(api_client, auth_headers, published_article):
    data = {"isHelpful": True, "comment": "Good"}
    response = api_client.post(f"/api/v1/help/articles/{published_article.slug}/feedback/", data, format="json")
    assert response.status_code == 201

def test_get_faqs_with_keyword_search(api_client, faq_factory, category):
    faq1 = faq_factory(category=category, question="How to setup Telebirr?", status="published")
    faq2 = faq_factory(category=category, question="How to submit project?", status="published")
    
    response = api_client.get("/api/v1/help/faqs/?keyword=Telebirr")
    assert response.status_code == 200
    assert len(response.data["data"]) == 1
    assert response.data["data"][0]["question"] == "How to setup Telebirr?"

