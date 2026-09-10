from django.urls import path
from . import views

urlpatterns = [
    path("categories/", views.CategoryListView.as_view()),
    path("articles/", views.ArticleListView.as_view()),
    path("articles/<slug:slug>/", views.ArticleDetailView.as_view()),
    path("articles/<slug:slug>/feedback/", views.ArticleFeedbackView.as_view()),
    path("faqs/", views.FAQListView.as_view()),
    path("faqs/<uuid:id>/", views.FAQDetailView.as_view()),
    path("search/", views.ArticleSearchView.as_view()),
]
