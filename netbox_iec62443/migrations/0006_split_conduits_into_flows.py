"""
Move the data of the old model into the new one. Runs on its own (separate transaction from the schema changes).

- Zones get a type from their Purdue level: 3.5 is a DMZ, 4 and 5 are enterprise, everything else OT. Check
  external/supplier and safety zones by hand afterwards.
- Every flow (formerly a conduit) keeps its id, verdict, evidence, tags and history. Its free-text "protocols" and
  "via" cannot be turned into structured ports or hops, so they are kept in the comments. A verdict of yes or no is
  dated with the flow's last change. A two-way conduit becomes two flows: the original and a return flow.
- For every pair of zones that had flows between them, one IEC 62443-3-2 conduit is created joining the two zones,
  and their flows are assigned to it.
- Industrial services that listen (server, both) get a NetBox application service with their ports, bound to the IP
  addresses of their interface, and are linked to it. Clients, publishers and subscribers do not listen: their
  ports are dropped, and noted in the comments when they were not the protocol's defaults.

Not reversible: migrating back keeps the new data and drops what the old model cannot hold.
"""
from collections import defaultdict

from django.db import migrations

# Frozen copies of the plugin's protocol tables at the time of this migration
LABELS = {
    'modbus-tcp': 'Modbus TCP', 's7comm': 'S7comm', 's7comm-plus': 'S7comm-plus', 'profinet': 'PROFINET IO',
    'ethernet-ip': 'EtherNet/IP (CIP)', 'opc-ua': 'OPC UA', 'opc-da': 'OPC DA (DCOM)', 'dnp3': 'DNP3',
    'iec-104': 'IEC 60870-5-104', 'iec-61850-mms': 'IEC 61850 MMS', 'iec-61850-goose': 'IEC 61850 GOOSE',
    'bacnet-ip': 'BACnet/IP', 'knx-ip': 'KNXnet/IP', 'mqtt': 'MQTT', 'hart-ip': 'HART-IP', 'ethercat': 'EtherCAT',
    'omron-fins': 'Omron FINS', 'melsec': 'Mitsubishi MELSEC (SLMP)', 'other': 'Other',
}
DEFAULT_PORT_MAPPINGS = {
    'modbus-tcp': ['tcp/502'], 's7comm': ['tcp/102'], 's7comm-plus': ['tcp/102'],
    'ethernet-ip': ['tcp/44818', 'udp/2222'], 'opc-ua': ['tcp/4840'], 'opc-da': ['tcp/135'],
    'bacnet-ip': ['udp/47808'], 'dnp3': ['tcp/20000'], 'iec-104': ['tcp/2404'], 'iec-61850-mms': ['tcp/102'],
    'mqtt': ['tcp/1883', 'tcp/8883'], 'hart-ip': ['tcp/5094', 'udp/5094'], 'knx-ip': ['udp/3671'],
    'omron-fins': ['udp/9600'], 'melsec': ['tcp/5007'],
}
OLD_DEFAULT_PORTS = {
    'modbus-tcp': [502], 's7comm': [102], 's7comm-plus': [102], 'ethernet-ip': [44818, 2222], 'opc-ua': [4840],
    'opc-da': [135], 'bacnet-ip': [47808], 'dnp3': [20000], 'iec-104': [2404], 'iec-61850-mms': [102],
    'mqtt': [1883, 8883], 'hart-ip': [5094], 'knx-ip': [3671], 'omron-fins': [9600], 'melsec': [5007],
}
TRANSPORT = {'bacnet-ip': 'udp', 'knx-ip': 'udp', 'omron-fins': 'udp', 'profinet': 'udp'}
LISTENING_ROLES = ('server', 'both')
NOTE = 'netbox-iec62443 0.1.0 upgrade'


def _append(text, *notes):
    return '\n\n'.join([t for t in [(text or '').strip()] if t] + list(notes))


def zone_types(apps, schema_editor):
    Zone = apps.get_model('netbox_iec62443', 'Zone')
    Zone.objects.filter(purdue_level='3.5').update(zone_type='dmz')
    Zone.objects.filter(purdue_level__in=('4', '5')).update(zone_type='enterprise')


def flows(apps, schema_editor):
    Flow = apps.get_model('netbox_iec62443', 'Flow')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    TaggedItem = apps.get_model('extras', 'TaggedItem')
    flow_ct = ContentType.objects.filter(app_label='netbox_iec62443', model='flow').first()

    for flow in Flow.objects.order_by('pk'):
        notes = []
        if flow.protocols:
            notes.append(f'Protocols before the {NOTE} (free text): {flow.protocols}')
        if flow.via:
            notes.append(f'Via before the {NOTE} (free text): {flow.via}')
        update = {}
        if notes:
            update['comments'] = _append(flow.comments, *notes)
        if flow.allowed in ('yes', 'no') and flow.decided_on is None:
            update['decided_on'] = flow.last_updated.date() if flow.last_updated else None
        if update:
            # update() leaves last_updated alone
            Flow.objects.filter(pk=flow.pk).update(**update)
        if flow.direction != 'two-way':
            continue
        name, n = f'{flow.name} (return)'[:100], 2
        while Flow.objects.filter(source_zone_id=flow.destination_zone_id, destination_zone_id=flow.source_zone_id,
                                  name=name).exists():
            name, n = f'{flow.name[:88]} (return {n})', n + 1
        reverse = Flow.objects.create(
            name=name,
            source_zone_id=flow.destination_zone_id,
            destination_zone_id=flow.source_zone_id,
            allowed=flow.allowed,
            decided_on=update.get('decided_on', flow.decided_on),
            remote_access=flow.remote_access,
            evidence=flow.evidence,
            description=flow.description,
            comments=_append(update.get('comments', flow.comments),
                             f'Return direction of the two-way conduit "{flow.name}" (#{flow.pk}), split in the '
                             f'{NOTE}.'),
            custom_field_data=flow.custom_field_data,
            owner_id=flow.owner_id,
            direction='one-way',
        )
        if flow_ct:
            TaggedItem.objects.bulk_create([
                TaggedItem(tag_id=item.tag_id, content_type_id=flow_ct.pk, object_id=reverse.pk)
                for item in TaggedItem.objects.filter(content_type_id=flow_ct.pk, object_id=flow.pk)
            ])


def conduits(apps, schema_editor):
    Flow = apps.get_model('netbox_iec62443', 'Flow')
    Conduit = apps.get_model('netbox_iec62443', 'Conduit')
    Zone = apps.get_model('netbox_iec62443', 'Zone')
    pairs = defaultdict(list)
    for pk, src, dst in Flow.objects.values_list('pk', 'source_zone_id', 'destination_zone_id'):
        pairs[frozenset((src, dst))].append(pk)
    zones = Zone.objects.in_bulk(set().union(*pairs) if pairs else [])
    for pair, flow_pks in pairs.items():
        a, b = sorted((zones[pk] for pk in pair), key=lambda z: (z.name, z.pk))
        site_id = a.site_id if a.site_id == b.site_id else None if (a.site_id and b.site_id) else (a.site_id or
                                                                                                   b.site_id)
        base = f'{a.name} - {b.name}'[:100]
        name, n = base, 2
        while Conduit.objects.filter(site_id=site_id, name=name).exists():
            name, n = f'{base[:94]} ({n})', n + 1
        conduit = Conduit.objects.create(
            name=name,
            site_id=site_id,
            description=f'Created from the flows between {a.name} and {b.name} in the {NOTE}'[:200],
            custom_field_data={},
        )
        conduit.zones.set([a.pk, b.pk])
        Flow.objects.filter(pk__in=flow_pks).update(conduit=conduit)


def industrial_services(apps, schema_editor):
    IndustrialService = apps.get_model('netbox_iec62443', 'IndustrialService')
    Service = apps.get_model('ipam', 'Service')
    IPAddress = apps.get_model('ipam', 'IPAddress')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    def ct(app_label, model):
        return ContentType.objects.get_or_create(app_label=app_label, model=model)[0]

    for svc in IndustrialService.objects.exclude(ports=[]).order_by('pk'):
        if svc.role not in LISTENING_ROLES:
            if sorted(svc.ports) != sorted(OLD_DEFAULT_PORTS.get(svc.protocol, [])):
                ports = ', '.join(str(p) for p in svc.ports)
                IndustrialService.objects.filter(pk=svc.pk).update(comments=_append(
                    svc.comments, f'Ports before the {NOTE}: {ports} (a {svc.role} does not listen, so they were not '
                                  f'moved to an application service).'))
            continue
        mappings = []
        for port in svc.ports:
            defaults = [m for m in DEFAULT_PORT_MAPPINGS.get(svc.protocol, []) if m.endswith(f'/{port}')]
            for mapping in defaults or [f"{TRANSPORT.get(svc.protocol, 'tcp')}/{port}"]:
                if mapping not in mappings:
                    mappings.append(mapping)
        if svc.device_id:
            parent_ct, parent_id = ct('dcim', 'device'), svc.device_id
        else:
            parent_ct, parent_id = ct('virtualization', 'virtualmachine'), svc.virtual_machine_id
        service = Service.objects.filter(parent_object_type=parent_ct, parent_object_id=parent_id,
                                         port_mappings=mappings).first()
        if service is None:
            service = Service.objects.create(
                parent_object_type=parent_ct,
                parent_object_id=parent_id,
                name=LABELS.get(svc.protocol, svc.protocol)[:100],
                port_mappings=mappings,
                description=f'Created from industrial service #{svc.pk} in the {NOTE}'[:200],
                custom_field_data={},
            )
        if svc.interface_id:
            service.ipaddresses.add(*IPAddress.objects.filter(
                assigned_object_type=ct('dcim', 'interface'), assigned_object_id=svc.interface_id,
            ))
        IndustrialService.objects.filter(pk=svc.pk).update(service=service)


def forward(apps, schema_editor):
    zone_types(apps, schema_editor)
    flows(apps, schema_editor)
    conduits(apps, schema_editor)
    industrial_services(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('extras', '0144_customfield_status'),
        ('ipam', '0097_merge_ipaddress_host_index_and_multi_protocol_services'),
        ('netbox_iec62443', '0005_conduit_flowhop_flow_fields'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
