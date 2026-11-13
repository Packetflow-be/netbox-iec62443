"""
The large demo plant of `manage.py ot_demo --large`: 35 zones (three production lines with sub-zones, utilities,
site operations, a DMZ, the office and three suppliers) and about 200 flows, without devices. It is there to
see the access map, the lists and the register at the size of a real plant; the small demo stays the one to
learn the plugin with. Everything belongs to its own site, and `--large --delete` removes exactly that.
"""
import datetime

from django.utils import timezone

SITE_SLUG = 'iec62443-demo-large'
PREFIX = 'IEC 62443 demo large'
LINES = (1, 2, 3)
UTILITIES = ('Boiler house', 'Compressed air', 'Water treatment')


def delete_large():
    from dcim.models import Site

    from netbox_ot.models import Flow, Zone

    site = Site.objects.filter(slug=SITE_SLUG).first()
    zones = Zone.objects.filter(site=site) | Zone.objects.filter(slug__startswith=SITE_SLUG, site__isnull=True)
    Flow.objects.filter(source_zone__in=zones).delete()
    Flow.objects.filter(destination_zone__in=zones).delete()
    zones.filter(parent__isnull=False).delete()
    zones.delete()
    if site:
        site.delete()


def create_large():
    from dcim.models import Site

    from netbox_ot.models import Flow, Zone

    today = timezone.localdate()
    now = timezone.now()
    site = Site.objects.create(name=f'{PREFIX} plant', slug=SITE_SLUG,
                               description='Fictional plant created by manage.py ot_demo --large')
    z = {}

    def zone(name, level, zone_type='ot', parent=None, external=False):
        z[name] = Zone.objects.create(
            name=f'{name} ({PREFIX})' if external else name,
            slug=(f'{SITE_SLUG}-' if external else '') + name.lower().replace(' ', '-'),
            site=None if external else site, purdue_level=level, zone_type=zone_type,
            parent=z[parent] if parent else None)

    for name in ('Internet', 'Corporate WAN'):
        zone(name, '5', 'enterprise')
    for name in ('Office', 'ERP', 'IT management', 'Guest Wi-Fi'):
        zone(name, '4', 'enterprise')
    for name in ('DMZ historian mirror', 'DMZ remote access', 'DMZ patch and antivirus', 'DMZ MQTT broker'):
        zone(name, '3.5', 'dmz')
    for name in ('MES', 'Site historian', 'Engineering', 'OT management'):
        zone(name, '3')
    for n in LINES:
        zone(f'Control room line {n}', '2')
        zone(f'Line {n} cell', '1')
        zone(f'Line {n} robots', '1', parent=f'Line {n} cell')
        zone(f'Line {n} safety', '1', 'safety', parent=f'Line {n} cell')
    zone('Control room utilities', '2')
    for name in UTILITIES:
        zone(name, '1')
    for name in ('Tank farm instruments', 'Packaging sensors'):
        zone(name, '0')
    for name in ('MSP', 'Robot supplier', 'Boiler supplier'):
        zone(name, '', 'external', external=True)

    seen = {'first_seen': now - datetime.timedelta(days=30), 'last_seen': now - datetime.timedelta(days=1)}
    evidence = 'Passively seen in the demo capture (4 weeks, SPAN on the OT core switches).'
    count = 0

    def flow(src, dst, protocol, port, access=(), allowed='yes', name='', **kwargs):
        nonlocal count
        count += 1
        Flow.objects.create(
            source_zone=z[src], destination_zone=z[dst], protocol=protocol, port_mappings=[port] if port else [],
            access=list(access), allowed=allowed, name=name, evidence=evidence, **{**seen, **kwargs})

    expired = {'expires': today - datetime.timedelta(days=20)}
    for n in LINES:
        room, cell, robots, safety = f'Control room line {n}', f'Line {n} cell', f'Line {n} robots', f'Line {n} safety'
        flow(room, cell, 's7comm', 'tcp/102', ['read', 'write'])
        flow(room, cell, 's7comm', 'tcp/102', ['program', 'control'], name=f'Line {n} engineering station')
        flow(room, cell, 'opc-ua', 'tcp/4840', ['read'])
        flow(room, robots, 'ethernet-ip', 'tcp/44818', ['read', 'write'])
        flow(room, robots, 'http', 'tcp/80', ['read'], 'unknown')
        flow(room, safety, 's7comm', 'tcp/102', ['read'])
        flow(cell, robots, 'profinet', '', ['read', 'write'])
        flow(robots, cell, 'profinet', '', ['read'])
        flow(safety, cell, 'profinet', '', ['control'])
        flow('MES', room, 'opc-ua', 'tcp/4840', ['read'])
        flow('MES', cell, 'opc-ua', 'tcp/4843', ['read', 'write'], 'unknown' if n == 2 else 'yes',
             connection='reverse-connect' if n == 2 else 'client-server')
        flow('Site historian', room, 'opc-ua', 'tcp/4840', ['read'])
        flow('Site historian', cell, 'modbus-tcp', 'tcp/502', ['read'])
        flow('Engineering', cell, 's7comm', 'tcp/102', ['program'], **(expired if n == 3 else {}))
        flow('Engineering', robots, 'ssh', 'tcp/22', [], 'unknown')
        flow('Engineering', safety, 's7comm', 'tcp/102', ['program'], 'no' if n == 1 else 'yes')
        flow('OT management', cell, 'snmp', 'udp/161', ['read'])
        flow('OT management', room, 'rdp', 'tcp/3389')
        flow('OT management', room, 'ntp', 'udp/123')
        flow('OT management', cell, 'ntp', 'udp/123')
        flow('DMZ patch and antivirus', room, 'https', 'tcp/443')
        flow(cell, 'DMZ MQTT broker', 'mqtt', 'tcp/8883', ['write'])
        flow(room, 'OT management', 'syslog', 'udp/514')
        flow(cell, 'OT management', 'syslog', 'udp/514')
        flow(room, 'Site historian', 'opc-ua', 'tcp/4840', ['write'], 'unknown')
        flow('Robot supplier', robots, 'teamviewer', 'tcp/5938', [], ('yes', 'unknown', 'yes')[n - 1],
             remote_access=True, name=f'Robot supplier TeamViewer line {n}', **(expired if n == 1 else {}))
        flow('MSP', room, 'rdp', 'tcp/3389', [], remote_access=True, name=f'MSP maintenance line {n}')
        flow('ERP', cell, 'mqtt', 'tcp/8883', ['write'], 'unknown', connection='brokered',
             broker_zone=z['DMZ MQTT broker'], topics=[f'spBv1.0/line{n}/DCMD/#'], name=f'Recipes line {n}')
        flow(cell, 'Packaging sensors', 'modbus-tcp', 'tcp/502', ['read'])
        flow(robots, 'Packaging sensors', 'ethernet-ip', 'tcp/44818', ['read', 'write'])
        flow('Site historian', robots, 'ethernet-ip', 'tcp/44818', ['read'])
        flow('MES', robots, 'ethernet-ip', 'tcp/44818', ['read'], 'unknown')
        flow('Engineering', room, 'rdp', 'tcp/3389')
        flow(room, 'Engineering', 'smb', 'tcp/445', ['read', 'write'], name=f'Line {n} project files')
        flow(room, 'OT management', 'smb', 'tcp/445', ['write'], name=f'Line {n} backups')
        flow(safety, room, 'opc-ua', 'tcp/4840', ['read'], name=f'Line {n} safety alarms')
    flow('Office', 'Line 1 cell', 'modbus-tcp', 'tcp/502', ['read', 'write'], 'no',
         description='Office laptop writing to the line - should not exist')
    flow('Guest Wi-Fi', 'Control room line 2', 'smb', 'tcp/445', [], 'unknown',
         comments='Found in the capture; nobody knows why yet')
    flow('Office', 'Control room line 3', 'vnc', 'tcp/5900', [], 'no')
    flow('Line 1 cell', 'Line 2 cell', 's7comm', 'tcp/102', ['read', 'write'], 'unknown')
    flow('Line 2 cell', 'Line 3 cell', 's7comm', 'tcp/102', ['read'])
    flow('Control room line 1', 'Control room line 2', 'rdp', 'tcp/3389', [], 'unknown')

    for name in UTILITIES:
        flow('Control room utilities', name, 'modbus-tcp', 'tcp/502', ['read', 'write'])
        flow('Control room utilities', name, 'bacnet-ip', 'udp/47808', ['read'])
        flow('Site historian', name, 'modbus-tcp', 'tcp/502', ['read'])
        flow('OT management', name, 'snmp', 'udp/161', ['read'])
        flow('OT management', name, 'ntp', 'udp/123')
        flow(name, 'OT management', 'syslog', 'udp/514')
        flow(name, 'Tank farm instruments', 'hart-ip', 'tcp/5094', ['read', 'write'],
             'unknown' if name == 'Compressed air' else 'yes')
        flow('Engineering', name, 'modbus-tcp', 'tcp/502', ['program'], name=f'Engineering {name.lower()}')
        flow('MES', name, 'opc-ua', 'tcp/4840', ['read'])
    flow('Boiler supplier', 'Boiler house', 'vnc', 'tcp/5900', [], 'no', remote_access=True,
         name='Boiler supplier 4G router')
    flow('Boiler supplier', 'Control room utilities', 'https', 'tcp/443', [], remote_access=True, **expired)
    flow('MES', 'Control room utilities', 'opc-ua', 'tcp/4840', ['read'])
    flow('Site historian', 'Control room utilities', 'opc-ua', 'tcp/4840', ['read'])
    flow('OT management', 'Control room utilities', 'rdp', 'tcp/3389')
    flow('OT management', 'Control room utilities', 'ntp', 'udp/123')
    flow('DMZ patch and antivirus', 'Control room utilities', 'https', 'tcp/443')
    flow('Control room utilities', 'OT management', 'syslog', 'udp/514')
    flow('Water treatment', 'Line 3 cell', 'modbus-tcp', 'tcp/502', ['read'], 'unknown')

    # Site operations, the DMZ and the office
    for name in ('MES', 'Site historian', 'Engineering', 'OT management'):
        flow('DMZ patch and antivirus', name, 'https', 'tcp/443')
        flow('DMZ remote access', name, 'rdp', 'tcp/3389', [], 'yes' if name == 'Engineering' else 'unknown')
    flow('DMZ remote access', 'Engineering', 'ssh', 'tcp/22')
    flow('Site historian', 'DMZ historian mirror', 'https', 'tcp/443', ['write'])
    flow('MES', 'DMZ MQTT broker', 'mqtt', 'tcp/8883', ['write'])
    flow('MES', 'ERP', 'https', 'tcp/443', ['write'])
    flow('ERP', 'MES', 'https', 'tcp/443', ['write'])
    flow('ERP', 'DMZ MQTT broker', 'mqtt', 'tcp/8883', ['read'])
    flow('Office', 'DMZ historian mirror', 'https', 'tcp/443', ['read'])
    flow('Office', 'ERP', 'https', 'tcp/443', ['read', 'write'])
    flow('Office', 'DMZ remote access', 'rdp', 'tcp/3389', [], 'unknown')
    flow('IT management', 'DMZ patch and antivirus', 'https', 'tcp/443', ['write'])
    flow('IT management', 'DMZ remote access', 'ssh', 'tcp/22')
    flow('IT management', 'OT management', 'rdp', 'tcp/3389', [], 'no')
    flow('IT management', 'Office', 'smb', 'tcp/445')
    flow('Guest Wi-Fi', 'Office', 'smb', 'tcp/445', [], 'no')
    flow('Guest Wi-Fi', 'Internet', 'https', 'tcp/443')
    flow('Corporate WAN', 'Office', 'https', 'tcp/443')
    flow('Corporate WAN', 'ERP', 'https', 'tcp/443')
    flow('Office', 'Internet', 'https', 'tcp/443')
    flow('Internet', 'DMZ remote access', 'ipsec', 'udp/500', [], remote_access=True)
    flow('MSP', 'DMZ remote access', 'ipsec', 'udp/500', [], remote_access=True, name='MSP VPN')
    flow('MSP', 'OT management', 'ssh', 'tcp/22', [], 'unknown', remote_access=True)
    flow('Robot supplier', 'DMZ remote access', 'https', 'tcp/443', [], remote_access=True)
    for name in ('MES', 'Site historian', 'Engineering'):
        flow('OT management', name, 'ssh', 'tcp/22')
    flow('Control room utilities', 'OT management', 'smb', 'tcp/445', ['write'], name='Utilities backups')
    flow('Office', 'MES', 'https', 'tcp/443', ['read'], 'unknown')
    flow('ERP', 'Site historian', 'https', 'tcp/443', ['read'])
    flow('Corporate WAN', 'IT management', 'ssh', 'tcp/22')
    flow('IT management', 'ERP', 'ssh', 'tcp/22')
    flow('IT management', 'Guest Wi-Fi', 'https', 'tcp/443')
    return site, len(z), count
