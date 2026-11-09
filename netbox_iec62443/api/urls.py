from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register('zones', views.ZoneViewSet)
router.register('conduits', views.ConduitViewSet)

urlpatterns = router.urls
