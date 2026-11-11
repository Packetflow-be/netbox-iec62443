# Changelog

## Unreleased

- `--branch NAME` on `iec62443_demo`, `iec62443_import`, `iec62443_check` and `iec62443_rules`: the command
  runs in that branch of the [netbox-branching](https://github.com/netboxlabs/netbox-branching) plugin instead
  of main. Without the option nothing changes, and netbox-branching stays optional (#9).

## 0.2.0 (2026-11-11)

- `iec62443_import --unknown-import DIR` writes the unknown hosts inside a zone as NetBox bulk-import files
  (devices, interfaces, IP addresses), for a first visit where NetBox does not know the plant's devices yet.
  The importer still creates no devices itself: a person names the role and device type first.

## 0.1.0 (2026-11-11)

First release, for NetBox 4.7 (4.7.0 and later; 4.8 allowed).

- Packaging for PyPI, CI on NetBox 4.7.0, the newest 4.7 release and NetBox's development branch, and
  publishing to PyPI from a version tag.
- `manage.py iec62443_demo` creates a populated fictional plant (and `--delete` removes it), so a new user sees
  the access map, register and checks within minutes.

- Zone, Conduit, Flow and Flow hop models with UI views, bulk import/edit/delete, filters, search, REST API
  and GraphQL.
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
- Consistency checks (UI page, REST `checks/`, `manage.py iec62443_check` with an exit code for CI) and a
  per-site zone register (site tab, printable, CSV per table, REST `register/`).
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
  remote access.
- Every import reports the observed hosts that match nothing in NetBox; `--unknown-report` writes them to CSV.
- Vendor-neutral firewall rules from the allowed flows (per site or per enforcing device; CSV or JSON): REST
  `firewall-rules/`, `manage.py iec62443_rules`, and a CSV on the site's zone register.
- Deleting a zone that still has flows is refused, so verdicts and evidence are never lost.
- Industrial services (protocol, role, NetBox application service with the ports, or fieldbus/address) and
  fieldbuses (medium, protocol, zone, gateway), with UI, API, GraphQL and the device panel.
- English only; all strings translatable, so the UI follows NetBox's language once translations exist.

### Upgrading from a 0.1.0.dev0 development build

The old conduit model (a directed zone pair with a verdict) becomes the flow model; migrations 0004-0007
move the data and delete nothing. See "Upgrading from a 0.1.0.dev0 development build" in the README for what
happens to two-way conduits, free-text protocols and via, and industrial service ports. Migrations
0008-0010 turn a single SL-T number into the vector with that level for every FR. The data migration
writes no change-log entries. Right after `migrate` the plugin extends every permission on flows to conduits
and flow hops (not when it has constraints) and rebuilds the search index of its models. The REST endpoint
`access-map/` returns `flows` where it returned `conduits`, without the SVG diagram.
