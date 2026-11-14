<h1><img src="https://raw.githubusercontent.com/Packetflow-be/netbox-ot/main/docs/icon.svg" alt="" width="44" height="44" align="absmiddle">&nbsp;netbox-ot</h1>

**An OT asset and security register in NetBox: IEC 62443 zones, conduits and flows, who can reach your PLCs and
who decided that is allowed.**

*Formerly **netbox-iec62443**: 0.3.0 takes an existing installation over in place, see
[Upgrading from netbox-iec62443](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/installation.md#from-netbox-iec62443).*

[![PyPI](https://img.shields.io/pypi/v/netbox-ot)](https://pypi.org/project/netbox-ot/)
[![CI](https://github.com/Packetflow-be/netbox-ot/actions/workflows/ci.yml/badge.svg)](https://github.com/Packetflow-be/netbox-ot/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/netbox-ot)](https://github.com/Packetflow-be/netbox-ot/blob/main/LICENSE)

A NetBox plugin for OT networks. It models **IEC 62443 zones and conduits**, the **flows** that run through
them, and **Purdue levels** on devices and virtual machines. On top of that it builds an **access map**: every
known flow into the controller zones, each with an "allowed?" verdict and who decided it.

It is meant for the people who run production networks: plant and maintenance engineers, OT/IT teams and the
integrators who work for them. Keep zones, conduits and industrial protocols in the same NetBox as the rest of
your inventory. See at a glance who can reach the PLCs, including supplier remote access over 4G routers,
TeamViewer, VPN or an MSP's jump host, and decide per flow whether that is allowed. Then hand an auditor the
zone register.

![The demo plant: the OT overview, the access map, a flow with its verdict and path, a zone with its security levels, and the zone register](https://raw.githubusercontent.com/Packetflow-be/netbox-ot/main/docs/demo.gif)

## Features

- **Zones and conduits** per IEC 62443-3-2: zone types (OT, safety/SIS, DMZ, enterprise, supplier), Purdue
  levels, SL-T and SL-A vectors over the seven foundational requirements, accountable people, sub-zones, the
  devices that enforce a conduit, and risk assessments. [Data model](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/data-model.md)
- **Flows**: what actually runs from one zone into another (protocol, ports, read/write/control/program access,
  remote access, the path of hops it takes, how the ends connect: client/server, OPC UA Reverse Connect or
  through an MQTT broker) with a verdict: allowed yes/no/unknown, decided by whom, review
  and expiry dates.
- **Access map** per site: the flows into the controller zones, worst first, with what needs attention and a
  diagram. [Access map](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/access-map.md)
- **OT overview** per site: achieved against target security level per foundational requirement as a radar
  chart, the zones furthest below target, requirement statuses and risk before and after countermeasures.
  [OT overview](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/overview.md)
- **Consistency checks** and a printable **zone register** (CSV, JSON) for the audit, also as an API and a
  command with an exit code for CI. [Checks and register](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/checks-and-register.md)
- **Industrial services and fieldbuses**: Modbus, S7comm, PROFINET, EtherNet/IP, OPC UA, DNP3, IEC 61850 and
  more, linked to NetBox application services. [Industrial systems](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/industrial.md)
- **Importer** for passive captures: Zeek logs (with or without CISA ICSNPP) or a documented JSON format, with
  a list of the hosts NetBox does not know yet. [Importer](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/importer.md)
- **System requirements** (IEC 62443-3-3) and their status per zone or conduit, for the audit; identifiers ship,
  the texts and levels come from your own copy of the standard.
  [System requirements](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/requirements.md)
- **Vendor-neutral firewall rules** from the allowed flows. [Firewall rules](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/firewall-rules.md)
- **Lifecycle**: end of support per device from netbox-lifecycle (device type and modules), checks for
  unsupported devices in secure zones, and a firmware version field on devices and modules.
  [Companion plugins](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/companions.md)
- **Branches**: with netbox-branching (separately licensed, optional) the commands take `--branch`, and
  *OT > Settings* sets a default branch for imports and can refuse imports into main. Not recommended:
  branches have to be rebuilt after every netbox-ot upgrade with a migration; `ot_import --dry-run` is the
  lighter way to try an import.
  [Working in a branch](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/branching.md)
- REST API, GraphQL, filters, bulk import/edit, change log and permissions like any NetBox object.
  [API](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/api.md)

## Compatibility

| Plugin | NetBox | Python |
|---|---|---|
| 0.4.x, 0.3.x (netbox-ot) | 4.7.0 and later 4.7 releases; 4.8 allowed | 3.12, 3.13 |
| 0.2.x, 0.1.x (as netbox-iec62443) | 4.7.0 and later 4.7 releases; 4.8 allowed | 3.12, 3.13 |

CI runs the full test suite on NetBox 4.7.0, on the newest 4.7 release, and every week on NetBox's
development branch for the next release, so a NetBox change that breaks the plugin shows up before it ships.
`max_version` admits 4.8 on the strength of that weekly run; it is lowered again if the next release breaks
the plugin.

## Dependencies

None: no other NetBox plugins, Python packages, external software or services. The importer reads files that
other tools wrote; to import from network captures you need [Zeek](https://zeek.org/) (optionally with the
[CISA ICSNPP](https://github.com/cisagov/ICSNPP) parsers, or [Malcolm](https://github.com/cisagov/Malcolm),
which bundles both) somewhere, not on the NetBox server.

**Works with** [netbox-lifecycle](https://github.com/DanSheps/netbox-lifecycle) (end of support per device,
checks for unsupported devices in secure zones) and [netbox-inventory](https://github.com/ArnesSI/netbox-inventory)
(spares and purchases), tested together in CI; both optional. See
[Companion plugins](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/companions.md).

## Installation

For a NetBox installed from source in `/opt/netbox`:

```bash
cd /opt/netbox
echo "netbox-ot" | sudo tee -a local_requirements.txt
sudo venv/bin/pip install netbox-ot
```

Add the plugin to `/opt/netbox/netbox/netbox/configuration.py` (if `PLUGINS` already exists, add it to the
list):

```python
PLUGINS = ["netbox_ot"]
```

Create its tables and restart:

```bash
sudo venv/bin/python netbox/manage.py migrate
sudo venv/bin/python netbox/manage.py collectstatic --no-input
sudo systemctl restart netbox netbox-rq
```

An *OT* menu appears. To see it populated within minutes, create the fictional demo plant and open the
site *IEC 62443 demo plant* (`--delete` removes it again):

```bash
sudo venv/bin/python netbox/manage.py ot_demo
```

[netbox-docker](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/installation.md#netbox-docker), the settings, permissions, upgrading and removing are in
[docs/installation.md](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/installation.md).

## Documentation

The full documentation is in [docs/](https://github.com/Packetflow-be/netbox-ot/blob/main/docs/README.md); release notes are in [CHANGELOG.md](https://github.com/Packetflow-be/netbox-ot/blob/main/CHANGELOG.md).

## Getting help and contributing

- **Questions and how-to**: [GitHub Discussions](https://github.com/Packetflow-be/netbox-ot/discussions).
- **Bugs and feature requests**: [GitHub issues](https://github.com/Packetflow-be/netbox-ot/issues). Please
  include the NetBox and plugin versions.
- **Security issues**: privately, as described in [SECURITY.md](https://github.com/Packetflow-be/netbox-ot/blob/main/SECURITY.md), not in a public issue.
- **Code, documentation and translations**: see [CONTRIBUTING.md](https://github.com/Packetflow-be/netbox-ot/blob/main/CONTRIBUTING.md).

The plugin is maintained by [Packetflow](https://packetflow.be), a small company in Belgium, and is in alpha:
the data model may still change, and every breaking change comes with a migration and a **Breaking Changes**
note in the changelog.

## License

Code: Apache License 2.0, see [LICENSE](https://github.com/Packetflow-be/netbox-ot/blob/main/LICENSE). The icon (`docs/icon.svg`) is licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
