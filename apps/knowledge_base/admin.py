from django.contrib import admin
from .models import Category, Article, ArticleVersion, FAQ, ArticleFeedback

admin.site.register(Category)
admin.site.register(Article)
admin.site.register(ArticleVersion)
admin.site.register(FAQ)
admin.site.register(ArticleFeedback)
