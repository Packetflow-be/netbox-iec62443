from django.urls import path

from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.register('zones', views.ZoneViewSet)
router.register('conduits', views.ConduitViewSet)
router.register('flows', views.FlowViewSet)
router.register('flow-hops', views.FlowHopViewSet)
router.register('risk-assessments', views.RiskAssessmentViewSet)
router.register('fieldbuses', views.FieldbusViewSet)
router.register('industrial-services', views.IndustrialServiceViewSet)

urlpatterns = router.urls + [
    path('access-map/', views.AccessMapAPIView.as_view(), name='accessmap'),
    path('checks/', views.ChecksAPIView.as_view(), name='checks'),
    path('register/', views.RegisterAPIView.as_view(), name='register'),
]
