from rest_framework.routers import DefaultRouter

app_name = "platform_admin"
router = DefaultRouter()
# router.register("example", views.ExampleViewSet, basename="example")

urlpatterns = router.urls
