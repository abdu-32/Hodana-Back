from rest_framework.routers import DefaultRouter

app_name = "accounts"
router = DefaultRouter()
# router.register("example", views.ExampleViewSet, basename="example")

urlpatterns = router.urls
