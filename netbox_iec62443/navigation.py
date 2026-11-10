from django.utils.translation import gettext_lazy as _

from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem


def _buttons(model):
    return (
        PluginMenuButton(
            link=f'plugins:netbox_iec62443:{model}_add', title=_('Add'), icon_class='mdi mdi-plus-thick',
            permissions=[f'netbox_iec62443.add_{model}'],
        ),
        PluginMenuButton(
            link=f'plugins:netbox_iec62443:{model}_bulk_import', title=_('Import'), icon_class='mdi mdi-upload',
            permissions=[f'netbox_iec62443.add_{model}'],
        ),
    )


menu = PluginMenu(
    label='IEC 62443',
    icon_class='mdi mdi-factory',
    groups=(
        (_('Zones, conduits and flows'), (
            PluginMenuItem(
                link='plugins:netbox_iec62443:zone_list', link_text=_('Zones'),
                permissions=['netbox_iec62443.view_zone'], buttons=_buttons('zone'),
            ),
            PluginMenuItem(
                link='plugins:netbox_iec62443:conduit_list', link_text=_('Conduits'),
                permissions=['netbox_iec62443.view_conduit'], buttons=_buttons('conduit'),
            ),
            PluginMenuItem(
                link='plugins:netbox_iec62443:flow_list', link_text=_('Flows'),
                permissions=['netbox_iec62443.view_flow'], buttons=_buttons('flow'),
            ),
            PluginMenuItem(
                link='plugins:netbox_iec62443:flowhop_list', link_text=_('Flow hops'),
                permissions=['netbox_iec62443.view_flowhop'], buttons=_buttons('flowhop'),
            ),
        )),
        (_('Risk'), (
            PluginMenuItem(
                link='plugins:netbox_iec62443:riskassessment_list', link_text=_('Risk assessments'),
                permissions=['netbox_iec62443.view_riskassessment'], buttons=_buttons('riskassessment'),
            ),
        )),
        (_('Industrial systems'), (
            PluginMenuItem(
                link='plugins:netbox_iec62443:industrialservice_list', link_text=_('Industrial services'),
                permissions=['netbox_iec62443.view_industrialservice'], buttons=_buttons('industrialservice'),
            ),
            PluginMenuItem(
                link='plugins:netbox_iec62443:fieldbus_list', link_text=_('Fieldbuses'),
                permissions=['netbox_iec62443.view_fieldbus'], buttons=_buttons('fieldbus'),
            ),
        )),
        (_('Reports'), (
            PluginMenuItem(
                link='plugins:netbox_iec62443:accessmap', link_text=_('Access map'),
                permissions=['netbox_iec62443.view_flow'],
            ),
            PluginMenuItem(
                link='plugins:netbox_iec62443:checks', link_text=_('Consistency checks'),
                permissions=['netbox_iec62443.view_zone'],
            ),
        )),
    ),
)
