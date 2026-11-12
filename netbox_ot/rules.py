"""
Vendor-neutral firewall rules from the flows a person decided on. One rule per flow and transport: the source
and destination zones with their networks, the transport and ports, and the action. It is a list for a firewall
team or a configuration tool to read; the plugin generates no vendor syntax and parses no vendor configuration.

  action        allow for an allowed flow; deny for a flow marked not allowed, or allowed but expired (only with
                include_denied). Flows without a verdict are not exported: they need a decision first.
  networks      the zone's prefixes, else the primary addresses of its members (/32). A zone with neither gives a
                rule with no networks and a note.
  ports         the flow's ports; when it has none, the protocol's usual ports, with a note that they were not
                observed. A layer-2 protocol (GOOSE, EtherCAT) gets transport "ethernet" and a note: a routed
                firewall cannot enforce it.
  enforced_by   the devices and VMs that enforce the flow's conduit, so a firewall can take its own rules.
  connection    a rule follows the connection a firewall sees, not the direction of the flow: a reverse-connect
                flow is opened by its destination zone towards its source zone; a flow through a broker becomes
                one rule from each end's zone to the broker zone (none for an end inside the broker zone).
"""
import csv
import io
import json
from collections import Counter, defaultdict

from django.utils import timezone

from .choices import ConnectionChoices, FlowAllowedChoices, FlowProtocolChoices
from .models import Flow

RULE_COLUMNS = (
    'rule', 'action', 'source_zone', 'source_networks', 'destination_zone', 'destination_networks', 'transport',
    'ports', 'application', 'connection', 'access', 'remote_access', 'conduit', 'enforced_by', 'valid_until',
    'decided_by', 'decided_on', 'flow_id', 'notes',
)
LAYER2 = ('iec-61850-goose', 'ethercat')


def zone_networks(zone):
    networks = [str(p.prefix) for p in zone.prefixes.all()]
    if networks:
        return networks
    addresses = [a.primary_ip4 for a in list(zone.devices.all()) + list(zone.virtual_machines.all()) if a.primary_ip4]
    return sorted({f'{ip.address.ip}/{32 if ip.address.version == 4 else 128}' for ip in addresses})


def _labels():
    labels = {}
    for item in FlowProtocolChoices.CHOICES:
        for value, label in (item[1] if isinstance(item[1], (list, tuple)) else [item]):
            labels[value] = str(label)
    return labels


def build_rules(flows=None, enforced_by=None, include_denied=False):
    """
    (rules, skipped): rules as dicts in RULE_COLUMNS order, allows first; skipped counts flows not exported by
    reason. `enforced_by` (a device or VM) keeps the flows whose conduit it enforces.
    """
    flows = (flows if flows is not None else Flow.objects.all()).select_related(
        'source_zone', 'destination_zone', 'broker_zone', 'conduit', 'decided_by',
    ).prefetch_related(
        *(f'{zone}__{members}' for zone in ('source_zone', 'destination_zone', 'broker_zone')
          for members in ('prefixes', 'devices__primary_ip4', 'virtual_machines__primary_ip4')),
        'conduit__enforcing_devices', 'conduit__enforcing_virtual_machines',
    )
    labels = _labels()
    connection_labels = {c[0]: str(c[1]) for c in ConnectionChoices.CHOICES}
    today = timezone.localdate()
    rules, skipped = [], Counter()
    for flow in flows.order_by('source_zone__name', 'destination_zone__name', 'name'):
        if flow.allowed == FlowAllowedChoices.UNKNOWN:
            skipped['no verdict yet'] += 1
            continue
        expired = flow.allowed == FlowAllowedChoices.YES and flow.expires and flow.expires < today
        action = 'allow' if flow.allowed == FlowAllowedChoices.YES and not expired else 'deny'
        if action == 'deny' and not include_denied:
            skipped['expired' if expired else 'not allowed'] += 1
            continue
        enforcers = []
        if flow.conduit:
            enforcers = list(flow.conduit.enforcing_devices.all()) + list(flow.conduit.enforcing_virtual_machines.all())
        if enforced_by is not None and enforced_by not in enforcers:
            skipped['enforced elsewhere'] += 1
            continue
        legs = flow.transport_legs
        if not legs:
            skipped['within the broker zone'] += 1
            continue
        flow_notes = []
        if expired:
            flow_notes.append(f'allowed until {flow.expires}, expired')
        if flow.connection == ConnectionChoices.REVERSE_CONNECT:
            flow_notes.append(f'reverse connect: {flow.destination_zone} opens the connection, '
                              f'{flow.source_zone} sends the requests')
        port_notes = []
        mappings = list(flow.port_mappings)
        if not mappings and flow.protocol in FlowProtocolChoices.DEFAULT_PORT_MAPPINGS:
            mappings = list(FlowProtocolChoices.DEFAULT_PORT_MAPPINGS[flow.protocol])
            port_notes.append('ports are the protocol default, not observed')
        by_transport = defaultdict(list)
        for mapping in mappings:
            transport, port = mapping.split('/')
            by_transport[transport].append(port)
        if not by_transport:
            if flow.protocol in LAYER2:
                by_transport['ethernet'] = []
                port_notes.append('layer 2: enforce with VLANs or switch ACLs, a routed firewall cannot')
            else:
                by_transport['any'] = []
                port_notes.append('no ports known')
        for initiating, accepting in legs:
            notes = list(flow_notes)
            if flow.connection == ConnectionChoices.BROKERED:
                role = 'publisher' if initiating == flow.source_zone else 'subscriber'
                notes.append(f'through a broker: the {role} connects to the broker in {accepting} '
                             f'(flow {flow.source_zone} -> {flow.destination_zone})')
            sources, destinations = zone_networks(initiating), zone_networks(accepting)
            if not sources:
                notes.append(f'{initiating} has no prefixes or member addresses')
            if not destinations:
                notes.append(f'{accepting} has no prefixes or member addresses')
            notes += port_notes
            for transport, ports in by_transport.items():
                rule_id = str(flow.pk)
                if len(legs) > 1:
                    rule_id += f'-{"pub" if initiating == flow.source_zone else "sub"}'
                if len(by_transport) > 1:
                    rule_id += f'-{transport}'
                rules.append({
                    'rule': rule_id,
                    'action': action,
                    'source_zone': initiating.name,
                    'source_networks': ' '.join(sources),
                    'destination_zone': accepting.name,
                    'destination_networks': ' '.join(destinations),
                    'transport': transport,
                    'ports': ','.join(ports),
                    'application': labels.get(flow.protocol, ''),
                    'connection': connection_labels.get(flow.connection, ''),
                    'access': ','.join(flow.access),
                    'remote_access': 'yes' if flow.remote_access else 'no',
                    'conduit': flow.conduit.name if flow.conduit else '',
                    'enforced_by': ' '.join(str(e) for e in enforcers),
                    'valid_until': flow.expires.isoformat() if flow.expires else '',
                    'decided_by': str(flow.decided_by or ''),
                    'decided_on': flow.decided_on.isoformat() if flow.decided_on else '',
                    'flow_id': flow.pk,
                    'notes': '; '.join(notes),
                })
    rules.sort(key=lambda r: r['action'] != 'allow')
    return rules, skipped


def rules_csv(rules):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=RULE_COLUMNS)
    writer.writeheader()
    writer.writerows(rules)
    return out.getvalue()


def rules_json(rules, skipped):
    return json.dumps({'rules': rules, 'not_exported': dict(skipped)}, indent=2)
