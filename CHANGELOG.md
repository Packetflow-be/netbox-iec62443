# Changelog

Each release opens with what kind of release it is. Breaking changes are listed under **Breaking Changes**.
Numbers link to the issue or pull request on GitHub; entries without a number predate the public repository.

## 0.3.0 (unreleased)

Minor release: **the plugin is renamed netbox-ot** (it was netbox-iec62443), because it grows beyond IEC 62443
into an OT asset and lifecycle register. An installation of netbox-iec62443 0.2.0 is taken over in place by the
first migration; see [Upgrading from netbox-iec62443](docs/installation.md#from-netbox-iec62443).

### Breaking Changes

- Package `netbox-ot`, Django app and `PLUGINS` entry `netbox_ot`, URLs `/plugins/ot/` and `/api/plugins/ot/`,
  menu *OT*.
- Commands `ot_import`, `ot_demo`, `ot_check`, `ot_rules` (were `iec62443_*`).
- Custom fields `ot_purdue_level` and `ot_sl_capability` (were `iec62443_*`; renamed with their values).
- Related names on NetBox models (`device.ot_zones`, ...) and the site tab URL `ot-register/`.
- The migrations are squashed into one `0001_initial`; the upgrade path from 0.1.0.dev0 development builds is
  gone (upgrade those to netbox-iec62443 0.2.0 first).

### Enhancements

- NetBox refuses to start with both `netbox_iec62443` and `netbox_ot` in `PLUGINS`, with a message that says
  what to do.
- CI upgrades a real netbox-iec62443 0.2.0 installation with the demo plant to this version on every run.

### Documentation

Changes from before the rename, documentation only:

- The README is a summary now, with the full documentation in [docs/](docs/README.md): installation and
  configuration (with a complete netbox-docker recipe and a settings table), data model, access map, checks and
  register, firewall rules, industrial systems, importer, API and commands, development.
- README: compatibility matrix per plugin version, dependencies, where to report bugs and ask questions, a
  demo GIF and the plugin icon (`docs/icon.svg`, CC BY 4.0).
- `SECURITY.md`, `CONTRIBUTING.md` and issue templates.

## 0.2.0 (2026-11-11)

Minor release with one new importer feature. No breaking changes; no new migrations.

### New features

- `iec62443_import --unknown-import DIR` writes the unknown hosts inside a zone as NetBox bulk-import files
  (devices, interfaces, IP addresses), for a first visit where NetBox does not know the plant's devices yet.
  The importer still creates no devices itself: a person names the role and device type first.
  ([#8](https://github.com/Packetflow-be/netbox-iec62443/pull/8))

## 0.1.0 (2026-11-11)

First release, for NetBox 4.7 (4.7.0 and later; 4.8 allowed): all features are new. Anyone who ran a
0.1.0.dev0 development build should read the breaking changes below; a new install is not affected.

### Breaking Changes

Only for installs of a 0.1.0.dev0 development build:

- The old *conduit* model (a directed zone pair with a verdict) becomes the *flow* model, and *conduit* is now
  the IEC 62443-3-2 object that joins zones. Migrations 0004-0007 move the data and delete nothing; see
  [Upgrading from a 0.1.0.dev0 development build](docs/installation.md#from-a-010dev0-development-build) for
  what happens to two-way conduits, free-text protocols and via, and industrial service ports. The data
  migration writes no change-log entries.
  ([#2](https://github.com/Packetflow-be/netbox-iec62443/pull/2))
- The REST endpoint `access-map/` returns `flows` where it returned `conduits`, without the SVG diagram.
  ([#2](https://github.com/Packetflow-be/netbox-iec62443/pull/2))
- A single SL-T number on a zone or conduit becomes the vector with that level for every FR (migrations
  0008-0010). ([#3](https://github.com/Packetflow-be/netbox-iec62443/pull/3))
- Right after `migrate` the plugin extends every permission on flows to conduits and flow hops (not when it has
  constraints) and rebuilds the search index of its models.
  ([#7](https://github.com/Packetflow-be/netbox-iec62443/pull/7))

### Features

- Zone, Conduit, Flow and Flow hop models with UI views, bulk import/edit/delete, filters, search, REST API
  and GraphQL. ([#2](https://github.com/Packetflow-be/netbox-iec62443/pull/2))
  - Zones have a type: OT, safety (SIS), DMZ, enterprise, external/supplier.
  - A conduit is the IEC 62443-3-2 object: it joins two or more zones, has its own SL-T and names the
    devices and VMs that enforce it.
  - A flow is one directed path from a source zone into a destination zone: protocol, ports (`tcp/102`),
    access (read, write, control, program), remote access, the ordered hops it runs through (devices, VMs,
    tunnels), the conduit that carries it, first/last seen and evidence.
  - A flow's verdict (allowed yes/no/unknown) records who decided it (a contact) and when, and can have a
    review date and an expiry date.
- Audit layer: SL-T and SL-A as vectors over the seven foundational requirements on zones and conduits, an
  accountable person (contact) on zones and conduits, sub-zones, and the IEC 62443-3-2 zone attributes wireless
  and temporarily connected devices (safety is a zone type). Risk assessments (initial/detailed, unmitigated,
  residual and tolerable risk, assessed/approved by and on, next review) with UI, API and GraphQL.
  ([#3](https://github.com/Packetflow-be/netbox-iec62443/pull/3))
- Consistency checks (UI page, REST `checks/`, `manage.py iec62443_check` with an exit code for CI) and a
  per-site zone register (site tab, printable, CSV per table, REST `register/`).
  ([#3](https://github.com/Packetflow-be/netbox-iec62443/pull/3))
- Purdue level custom field on devices and virtual machines, and an SL-C custom field on devices and device
  types, created after migrate. A zone's Purdue level is its most critical (lowest) level.
- Access map per site (table and diagram) on flows, as a site tab and as a standalone page: not allowed first,
  then allowed but expired, unknown, allowed. It lists what needs attention: expired access, verdicts due
  for review, flows not seen for `stale_after_days` (default 90), flows outside any conduit.
- IEC 62443 panel on device and VM pages: zones, their flows, conduits the asset enforces, flows through it.
- REST endpoint `access-map/` (the site's access-map flows) for reports and other tools.
- `iec62443_import` management command for observation files in a documented format
  (docs/import-format.md), with `--vrf`, `--outside-zone` and `--split`/`--split-all` (one zone per Purdue
  band).
  - Devices, VMs and prefixes are matched only at the import's site and in its VRF; ambiguous matches are
    skipped and reported. The importer links existing prefixes and never creates them.
    ([#1](https://github.com/Packetflow-be/netbox-iec62443/pull/1))
  - It creates one flow per zone pair and protocol, with the ports, times and access classes from the
    input, and puts a flow in a conduit only when exactly one conduit joins both zones.
  - OT requests are classified as read, write, control or program by an explicit table per protocol
    (Modbus, S7comm, S7comm-plus, EtherNet/IP, DNP3, IEC 104, IEC 61850 MMS, OPC UA, BACnet, Omron FINS),
    or by the flow's own `access` field. Remote access comes from the asset's `remote_access` field.
  - An open port alone creates no industrial service; protocols come from decoded traffic or the asset's
    `services` field. Unexplained open OT ports are listed in the import output.
- The importer reads Zeek logs directly (`--format zeek`, auto-detected): Zeek's own and the CISA ICSNPP
  protocol logs (Modbus, S7comm, S7comm-plus, EtherNet/IP and CIP, DNP3, BACnet, OPC UA, Omron FINS, HART-IP,
  PROFINET CM) and `conn.log`, TSV or JSON, gzipped and rotated files included. Zones come from NetBox (zone
  prefixes and members in the site and VRF) plus an optional `--zone-map` CSV. Flows from an external zone are
  remote access. ([#4](https://github.com/Packetflow-be/netbox-iec62443/pull/4))
- Every import reports the observed hosts that match nothing in NetBox; `--unknown-report` writes them to CSV.
  ([#4](https://github.com/Packetflow-be/netbox-iec62443/pull/4))
- Vendor-neutral firewall rules from the allowed flows (per site or per enforcing device; CSV or JSON): REST
  `firewall-rules/`, `manage.py iec62443_rules`, and a CSV on the site's zone register.
  ([#4](https://github.com/Packetflow-be/netbox-iec62443/pull/4))
- Deleting a zone that still has flows is refused, so verdicts and evidence are never lost.
  ([#1](https://github.com/Packetflow-be/netbox-iec62443/pull/1))
- Industrial services (protocol, role, NetBox application service with the ports, or fieldbus/address) and
  fieldbuses (medium, protocol, zone, gateway), with UI, API, GraphQL and the device panel.
- `manage.py iec62443_demo` creates a populated fictional plant (and `--delete` removes it), so a new user sees
  the access map, register and checks within minutes.
  ([#5](https://github.com/Packetflow-be/netbox-iec62443/pull/5))
- English only; all strings translatable, so the UI follows NetBox's language once translations exist.

### Packaging

- Packaging for PyPI, CI on NetBox 4.7.0, the newest 4.7 release and NetBox's development branch, and
  publishing to PyPI from a version tag. ([#5](https://github.com/Packetflow-be/netbox-iec62443/pull/5))
