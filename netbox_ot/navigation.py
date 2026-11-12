from django.apps import apps
from django.utils.translation import gettext_lazy as _

from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem


def _buttons(model):
    return (
        PluginMenuButton(
            link=f'plugins:netbox_ot:{model}_add', title=_('Add'), icon_class='mdi mdi-plus-thick',
            permissions=[f'netbox_ot.add_{model}'],
        ),
        PluginMenuButton(
            link=f'plugins:netbox_ot:{model}_bulk_import', title=_('Import'), icon_class='mdi mdi-upload',
            permissions=[f'netbox_ot.add_{model}'],
        ),
    )


groups = (
    (_('Zones, conduits and flows'), (
        PluginMenuItem(
            link='plugins:netbox_ot:zone_list', link_text=_('Zones'),
            permissions=['netbox_ot.view_zone'], buttons=_buttons('zone'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:conduit_list', link_text=_('Conduits'),
            permissions=['netbox_ot.view_conduit'], buttons=_buttons('conduit'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:flow_list', link_text=_('Flows'),
            permissions=['netbox_ot.view_flow'], buttons=_buttons('flow'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:flowhop_list', link_text=_('Flow hops'),
            permissions=['netbox_ot.view_flowhop'], buttons=_buttons('flowhop'),
        ),
    )),
    (_('Risk and requirements'), (
        PluginMenuItem(
            link='plugins:netbox_ot:riskassessment_list', link_text=_('Risk assessments'),
            permissions=['netbox_ot.view_riskassessment'], buttons=_buttons('riskassessment'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:requirementstatus_list', link_text=_('Requirement statuses'),
            permissions=['netbox_ot.view_requirementstatus'], buttons=_buttons('requirementstatus'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:systemrequirement_list', link_text=_('System requirements'),
            permissions=['netbox_ot.view_systemrequirement'], buttons=_buttons('systemrequirement'),
        ),
    )),
    (_('Industrial systems'), (
        PluginMenuItem(
            link='plugins:netbox_ot:industrialservice_list', link_text=_('Industrial services'),
            permissions=['netbox_ot.view_industrialservice'], buttons=_buttons('industrialservice'),
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:fieldbus_list', link_text=_('Fieldbuses'),
            permissions=['netbox_ot.view_fieldbus'], buttons=_buttons('fieldbus'),
        ),
    )),
    (_('Reports'), (
        PluginMenuItem(
            link='plugins:netbox_ot:accessmap', link_text=_('Access map'),
            permissions=['netbox_ot.view_flow'],
        ),
        PluginMenuItem(
            link='plugins:netbox_ot:checks', link_text=_('Consistency checks'),
            permissions=['netbox_ot.view_zone'],
        ),
    )),
)

# The settings page holds only the branching settings so far: without netbox-branching there is nothing to set
if apps.is_installed('netbox_branching'):
    groups += (
        (_('Settings'), (
            PluginMenuItem(
                link='plugins:netbox_ot:settings', link_text=_('Settings'),
                permissions=['netbox_ot.change_pluginsettings'],
            ),
        )),
    )

menu = PluginMenu(label='OT', icon_class='mdi mdi-factory', groups=groups)
