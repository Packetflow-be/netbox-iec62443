from django.urls import include, path

from utilities.urls import get_model_urls

from . import views

urlpatterns = [
    path('zones/', include(get_model_urls('netbox_ot', 'zone', detail=False))),
    path('zones/<int:pk>/', include(get_model_urls('netbox_ot', 'zone'))),
    path('conduits/', include(get_model_urls('netbox_ot', 'conduit', detail=False))),
    path('conduits/<int:pk>/', include(get_model_urls('netbox_ot', 'conduit'))),
    path('flows/', include(get_model_urls('netbox_ot', 'flow', detail=False))),
    path('flows/<int:pk>/', include(get_model_urls('netbox_ot', 'flow'))),
    path('flow-hops/', include(get_model_urls('netbox_ot', 'flowhop', detail=False))),
    path('flow-hops/<int:pk>/', include(get_model_urls('netbox_ot', 'flowhop'))),
    path('system-requirements/', include(get_model_urls('netbox_ot', 'systemrequirement', detail=False))),
    path('system-requirements/<int:pk>/', include(get_model_urls('netbox_ot', 'systemrequirement'))),
    path('requirement-statuses/', include(get_model_urls('netbox_ot', 'requirementstatus', detail=False))),
    path('requirement-statuses/<int:pk>/', include(get_model_urls('netbox_ot', 'requirementstatus'))),
    path('fieldbuses/', include(get_model_urls('netbox_ot', 'fieldbus', detail=False))),
    path('fieldbuses/<int:pk>/', include(get_model_urls('netbox_ot', 'fieldbus'))),
    path('industrial-services/', include(get_model_urls('netbox_ot', 'industrialservice', detail=False))),
    path('industrial-services/<int:pk>/', include(get_model_urls('netbox_ot', 'industrialservice'))),
    path('risk-assessments/', include(get_model_urls('netbox_ot', 'riskassessment', detail=False))),
    path('risk-assessments/<int:pk>/', include(get_model_urls('netbox_ot', 'riskassessment'))),
    path('access-map/', views.AccessMapView.as_view(), name='accessmap'),
    path('checks/', views.ChecksView.as_view(), name='checks'),
    path('settings/', views.PluginSettingsView.as_view(), name='settings'),
]
