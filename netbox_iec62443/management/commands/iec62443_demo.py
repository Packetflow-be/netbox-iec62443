"""
Demo data: a small fictional plant with zones, conduits, flows, services and risk assessments, so a new user sees
a populated access map, zone register and consistency checks within minutes. Everything it creates belongs to
the demo site (and the demo MSP zone, contacts, tenant group, VPN tunnel and roles named "IEC 62443 demo ..."),
and --delete removes exactly that.
"""
import datetime

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from netbox_iec62443.branching import BranchCommand

SITE_SLUG = 'iec62443-demo'
PREFIX = 'IEC 62443 demo'


class Command(BranchCommand):
    help = 'Create (or --delete) a demo plant to try the plugin: zones, conduits, flows, services, risk assessments'
    follows_settings = True

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='Remove the demo data instead')

    def handle(self, *args, **options):
        from dcim.models import Site
        if options['delete']:
            with transaction.atomic(using=self.db_alias):
                self._delete()
            self.stdout.write(self.style.SUCCESS('Demo data removed'))
            return
        if Site.objects.filter(slug=SITE_SLUG).exists():
            raise CommandError(f'The demo site "{SITE_SLUG}" already exists; remove it first with --delete')
        with transaction.atomic(using=self.db_alias):
            site = self._create()
        self.stdout.write(self.style.SUCCESS(
            f'Demo plant created: open the site "{site}" and its Access map and Zone register tabs, or '
            f'IEC 62443 > Consistency checks'))

    def _delete(self):
        from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
        from ipam.models import IPAddress, Prefix, Service
        from tenancy.models import Contact
        from virtualization.models import VirtualMachine
        from vpn.models import Tunnel

        from netbox_iec62443.models import Conduit, Fieldbus, Flow, IndustrialService, RiskAssessment, Zone

        site = Site.objects.filter(slug=SITE_SLUG).first()
        zones = Zone.objects.filter(site=site) | Zone.objects.filter(name=f'{PREFIX} MSP')
        conduits = Conduit.objects.filter(zones__in=zones).distinct()
        devices = Device.objects.filter(site=site)
        vms = VirtualMachine.objects.filter(site=site)
        RiskAssessment.objects.filter(zone__in=zones).delete()
        RiskAssessment.objects.filter(conduit__in=conduits).delete()
        Flow.objects.filter(source_zone__in=zones).delete()
        Flow.objects.filter(destination_zone__in=zones).delete()
        conduits.delete()
        IndustrialService.objects.filter(device__in=devices).delete()
        Fieldbus.objects.filter(site=site).delete()
        for asset in list(devices) + list(vms):
            Service.objects.filter(parent_object_id=asset.pk, parent_object_type__model=asset._meta.model_name).delete()
        zones.delete()
        Tunnel.objects.filter(name=f'{PREFIX} MSP IPsec').delete()
        for asset in list(vms) + list(devices):
            asset.delete()
        IPAddress.objects.filter(description=PREFIX).delete()
        Prefix.objects.filter(description__startswith=PREFIX).delete()
        if site:
            site.delete()
        Contact.objects.filter(description=PREFIX).delete()
        DeviceType.objects.filter(manufacturer__name=PREFIX).delete()
        Manufacturer.objects.filter(name=PREFIX).delete()
        DeviceRole.objects.filter(name__startswith=PREFIX).delete()

    def _create(self):
        from django.contrib.contenttypes.models import ContentType

        from dcim.models import Device, DeviceRole, DeviceType, Interface, Manufacturer, Site
        from ipam.models import IPAddress, Prefix, Service
        from tenancy.models import Contact
        from virtualization.models import VirtualMachine, VMInterface
        from vpn.models import Tunnel

        from netbox_iec62443.customfields import PURDUE_CF_NAME, SLC_CF_NAME
        from netbox_iec62443.models import (
            Conduit,
            Fieldbus,
            Flow,
            FlowHop,
            IndustrialService,
            RiskAssessment,
            Zone,
        )

        today = timezone.localdate()
        now = timezone.now()
        site = Site.objects.create(name=f'{PREFIX} plant', slug=SITE_SLUG,
                                   description='Fictional plant created by manage.py iec62443_demo')
        manager = Contact.objects.create(name='Demo plant manager', description=PREFIX)
        ot_lead = Contact.objects.create(name='Demo OT security lead', description=PREFIX)
        maker = Manufacturer.objects.create(name=PREFIX, slug='iec62443-demo')
        roles = {r: DeviceRole.objects.create(name=f'{PREFIX} {r}', slug=f'iec62443-demo-{r.lower()}')
                 for r in ('PLC', 'HMI', 'Firewall', 'Server', 'Gateway', 'Laptop')}
        types = {
            'plc': DeviceType.objects.create(manufacturer=maker, model='Demo PLC', slug='iec62443-demo-plc',
                                             custom_field_data={SLC_CF_NAME: '2,2,2,1,2,1,1'}),
            'hmi': DeviceType.objects.create(manufacturer=maker, model='Demo HMI panel', slug='iec62443-demo-hmi',
                                             custom_field_data={SLC_CF_NAME: '1'}),
            'fw': DeviceType.objects.create(manufacturer=maker, model='Demo OT firewall', slug='iec62443-demo-fw',
                                            custom_field_data={SLC_CF_NAME: '3'}),
            'box': DeviceType.objects.create(manufacturer=maker, model='Demo industrial PC', slug='iec62443-demo-pc'),
        }

        def prefix(cidr, label):
            return Prefix.objects.create(prefix=cidr, scope=site, description=f'{PREFIX} {label}')

        def device(name, kind, role, ip, level):
            d = Device.objects.create(name=name, site=site, device_type=types[kind], role=roles[role],
                                      custom_field_data={PURDUE_CF_NAME: level or None})
            iface = Interface.objects.create(device=d, name='eth0', type='1000base-t')
            d.primary_ip4 = IPAddress.objects.create(address=f'{ip}/24', assigned_object=iface,
                                                     description=PREFIX)
            d.save()
            return d

        def vm(name, ip, level):
            v = VirtualMachine.objects.create(name=name, site=site, custom_field_data={PURDUE_CF_NAME: level})
            iface = VMInterface.objects.create(virtual_machine=v, name='eth0')
            v.primary_ip4 = IPAddress.objects.create(address=f'{ip}/24', assigned_object=iface, description=PREFIX)
            v.save()
            return v

        # Zones
        cell = Zone.objects.create(name='Line 1 cell', slug='line-1-cell', site=site, purdue_level='1',
                                   sl_target=[2, 2, 2, 1, 2, 1, 2], sl_achieved=[2, 1, 2, 1, 2, 1, 2],
                                   accountable=manager, description='PLCs and drives of production line 1')
        sis = Zone.objects.create(name='Line 1 safety', slug='line-1-safety', site=site, purdue_level='1',
                                  zone_type='safety', parent=cell, sl_target=[3] * 7, accountable=manager)
        control = Zone.objects.create(name='Control room', slug='control-room', site=site, purdue_level='2',
                                      sl_target=[2] * 7, sl_achieved=[2] * 7, accountable=manager,
                                      temporary_devices=True)
        dmz = Zone.objects.create(name='OT DMZ', slug='ot-dmz', site=site, purdue_level='3.5', zone_type='dmz',
                                  sl_target=[2] * 7, accountable=ot_lead)
        office = Zone.objects.create(name='Office', slug='office', site=site, purdue_level='4',
                                     zone_type='enterprise', wireless=True)
        msp = Zone.objects.create(name=f'{PREFIX} MSP', slug='iec62443-demo-msp', zone_type='external',
                                  description='Managed service provider that maintains the SCADA servers')
        for zone, cidr in ((cell, '10.61.1.0/24'), (control, '10.61.2.0/24'), (dmz, '10.61.35.0/24'),
                           (office, '10.61.4.0/24')):
            zone.prefixes.add(prefix(cidr, zone.name))
        msp.prefixes.add(Prefix.objects.create(prefix='192.0.2.0/24', description=f'{PREFIX} MSP'))

        # Assets
        plc1 = device('demo-plc-1', 'plc', 'PLC', '10.61.1.10', '1')
        plc2 = device('demo-plc-2', 'plc', 'PLC', '10.61.1.11', '1')
        sis_plc = device('demo-sis-1', 'plc', 'PLC', '10.61.1.50', '1')
        gw = device('demo-gw-1', 'box', 'Gateway', '10.61.1.20', '1')
        hmi = device('demo-hmi-1', 'hmi', 'HMI', '10.61.2.10', '2')
        es = device('demo-es-1', 'box', 'Laptop', '10.61.2.20', '2')
        fw = device('demo-fw-1', 'fw', 'Firewall', '10.61.35.1', '3.5')
        historian = vm('demo-historian', '10.61.35.10', '3.5')
        jump = vm('demo-jump-1', '10.61.35.20', '3.5')
        laptop = device('demo-office-laptop', 'box', 'Laptop', '10.61.4.30', '4')
        device('demo-unzoned-camera', 'box', 'Gateway', '10.61.1.99', '')  # found by a capture, in no zone
        cell.devices.add(plc1, plc2, gw)
        sis.devices.add(sis_plc)
        control.devices.add(hmi, es)
        dmz.devices.add(fw)
        dmz.virtual_machines.add(historian, jump)
        office.devices.add(laptop)

        # Conduits
        c_control = Conduit.objects.create(name='Control room - Line 1', site=site, sl_target=[2] * 7,
                                           accountable=ot_lead)
        c_control.zones.set([control, cell])
        c_control.enforcing_devices.add(fw)
        c_dmz = Conduit.objects.create(name='DMZ - OT', site=site, sl_target=[2] * 7, accountable=ot_lead)
        c_dmz.zones.set([dmz, control, cell])
        c_dmz.enforcing_devices.add(fw)
        c_office = Conduit.objects.create(name='Office - DMZ', site=site, sl_target=[1] * 7)
        c_office.zones.set([office, dmz])
        c_office.enforcing_devices.add(fw)
        c_remote = Conduit.objects.create(name='Remote maintenance', site=site, sl_target=[3] * 7,
                                          accountable=ot_lead)
        c_remote.zones.set([msp, dmz])
        c_remote.enforcing_devices.add(fw)

        seen = {'first_seen': now - datetime.timedelta(days=14), 'last_seen': now - datetime.timedelta(days=1)}
        evidence = 'Passively seen in the demo capture (2 weeks, SPAN on the OT core switch).'

        def flow(src, dst, protocol, ports, access, allowed='unknown', **kwargs):
            return Flow.objects.create(source_zone=src, destination_zone=dst, protocol=protocol, port_mappings=ports,
                                       access=access, allowed=allowed, evidence=evidence, **{**seen, **kwargs})

        flow(control, cell, 's7comm', ['tcp/102'], ['read', 'write'], 'yes', conduit=c_control, decided_by=manager,
             review_by=today + datetime.timedelta(days=180))
        flow(control, cell, 's7comm', ['tcp/102'], ['program', 'control'], 'yes', name='Engineering station program',
             conduit=c_control, decided_by=ot_lead)
        flow(dmz, control, 'opc-ua', ['tcp/4840'], ['read'], 'yes', conduit=c_dmz, decided_by=ot_lead)
        flow(office, cell, 'modbus-tcp', ['tcp/502'], ['read', 'write'], 'no', decided_by=ot_lead,
             description='Office laptop writing to the line - should not exist')
        flow(office, control, 'smb', ['tcp/445'], [], comments='Found in the capture; nobody knows why yet')
        remote = flow(msp, dmz, 'rdp', ['tcp/3389'], [], 'yes', conduit=c_remote, remote_access=True,
                      decided_by=manager, expires=today + datetime.timedelta(days=30), name='MSP maintenance RDP')
        flow(msp, cell, 'teamviewer', ['tcp/5938'], [], 'yes', remote_access=True, decided_by=manager,
             expires=today - datetime.timedelta(days=10), name='Supplier TeamViewer (expired)')
        flow(cell, dmz, 'syslog', ['udp/514'], [], 'yes', conduit=c_dmz, decided_by=ot_lead)

        tunnel = Tunnel.objects.create(name=f'{PREFIX} MSP IPsec', status='active', encapsulation='ipsec-tunnel')
        for position, hop in enumerate((tunnel, jump, fw), start=1):
            field = {Tunnel: 'tunnel', VirtualMachine: 'virtual_machine', Device: 'device'}[type(hop)]
            FlowHop.objects.create(flow=remote, position=position, **{field: hop})

        # Industrial services and a fieldbus
        device_ct = ContentType.objects.get_for_model(Device)
        for plc in (plc1, plc2):
            core = Service.objects.create(parent_object_type=device_ct, parent_object_id=plc.pk, name='S7comm',
                                          port_mappings=['tcp/102'])
            core.ipaddresses.add(plc.primary_ip4)
            IndustrialService.objects.create(device=plc, protocol='s7comm', role='server', service=core,
                                             evidence=evidence)
        IndustrialService.objects.create(device=hmi, protocol='s7comm', role='client', evidence=evidence)
        bus = Fieldbus.objects.create(name='Line 1 RS-485', site=site, zone=cell, medium='rs-485',
                                      protocol='modbus-rtu', gateway=gw)
        for unit in (1, 2):
            IndustrialService.objects.create(device=gw, protocol='modbus-rtu', role='client', fieldbus=bus,
                                             address=f'unit {unit}' if unit == 1 else 'master')

        # Risk assessments
        RiskAssessment.objects.create(
            zone=cell, kind='detailed', status='approved', assessed_on=today - datetime.timedelta(days=200),
            assessed_by=ot_lead, approved_by=manager, approved_on=today - datetime.timedelta(days=190),
            next_review=today + datetime.timedelta(days=175), method='Demo company risk matrix (5x5)',
            threats='Malware brought in by a service laptop; unauthorised program change',
            consequences='Line stop; damaged product', unmitigated_risk='high',
            countermeasures='Engineering access only from the control room; firewall between DMZ and OT',
            residual_risk='medium', tolerable_risk='medium')
        RiskAssessment.objects.create(
            conduit=c_remote, kind='detailed', status='approved', assessed_on=today - datetime.timedelta(days=400),
            assessed_by=ot_lead, approved_by=manager, approved_on=today - datetime.timedelta(days=395),
            next_review=today - datetime.timedelta(days=30), threats='Compromised MSP account',
            unmitigated_risk='critical', countermeasures='Jump host with MFA, time-limited access',
            residual_risk='high', tolerable_risk='medium')
        RiskAssessment.objects.create(zone=office, kind='initial', assessed_on=today, unmitigated_risk='medium')
        return site
