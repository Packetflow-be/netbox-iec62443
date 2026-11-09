from django.urls import path

from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register('zones', views.ZoneViewSet)
router.register('conduits', views.ConduitViewSet)
router.register('fieldbuses', views.FieldbusViewSet)
router.register('industrial-services', views.IndustrialServiceViewSet)

urlpatterns = router.urls + [
    path('access-map/', views.AccessMapAPIView.as_view(), name='accessmap'),
]
