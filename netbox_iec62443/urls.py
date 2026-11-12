from django.urls import include, path

from utilities.urls import get_model_urls

from . import views

urlpatterns = [
    path('zones/', include(get_model_urls('netbox_iec62443', 'zone', detail=False))),
    path('zones/<int:pk>/', include(get_model_urls('netbox_iec62443', 'zone'))),
    path('conduits/', include(get_model_urls('netbox_iec62443', 'conduit', detail=False))),
    path('conduits/<int:pk>/', include(get_model_urls('netbox_iec62443', 'conduit'))),
    path('flows/', include(get_model_urls('netbox_iec62443', 'flow', detail=False))),
    path('flows/<int:pk>/', include(get_model_urls('netbox_iec62443', 'flow'))),
    path('flow-hops/', include(get_model_urls('netbox_iec62443', 'flowhop', detail=False))),
    path('flow-hops/<int:pk>/', include(get_model_urls('netbox_iec62443', 'flowhop'))),
    path('fieldbuses/', include(get_model_urls('netbox_iec62443', 'fieldbus', detail=False))),
    path('fieldbuses/<int:pk>/', include(get_model_urls('netbox_iec62443', 'fieldbus'))),
    path('industrial-services/', include(get_model_urls('netbox_iec62443', 'industrialservice', detail=False))),
    path('industrial-services/<int:pk>/', include(get_model_urls('netbox_iec62443', 'industrialservice'))),
    path('risk-assessments/', include(get_model_urls('netbox_iec62443', 'riskassessment', detail=False))),
    path('risk-assessments/<int:pk>/', include(get_model_urls('netbox_iec62443', 'riskassessment'))),
    path('access-map/', views.AccessMapView.as_view(), name='accessmap'),
    path('checks/', views.ChecksView.as_view(), name='checks'),
    path('settings/', views.PluginSettingsView.as_view(), name='settings'),
]
