from rest_framework.routers import DefaultRouter

app_name = "analytics"
router = DefaultRouter()
# router.register("example", views.ExampleViewSet, basename="example")

urlpatterns = router.urls
