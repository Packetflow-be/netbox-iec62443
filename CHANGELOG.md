# Changelog

Each release opens with what kind of release it is. Breaking changes are listed under **Breaking Changes**.
Numbers link to the issue or pull request on GitHub; entries without a number predate the public repository.

## 0.5.1 (2026-11-14)

Patch release with the fixes and usability changes from the second field review
([#35](https://github.com/Packetflow-be/netbox-ot/issues/35); pull requests
[#38](https://github.com/Packetflow-be/netbox-ot/pull/38) to [#43](https://github.com/Packetflow-be/netbox-ot/pull/43)):
the Zeek import no longer runs out of memory on a day of plant traffic and helps on a first visit, the OT
overview says what to do next right after an import, risk levels saved through the API are stored, and flows can
no longer join zones of two plants by accident. No migration and no breaking change. Two behaviour changes to
know about: a flow between OT zones of two different sites is refused (DMZ, enterprise and external zones may
still join sites), and the unknown-host import files name devices `unknown-<address>-<site slug>`.

### Enhancements

- **First Zeek import without zones** is no longer a dead end. An import into a site without zones lists the
  networks the conn log holds (per /24: hosts, connections, the services they answer) before it stops, and
  `--suggest-zone-map zones.csv` writes a draft zone map with one line per network no zone holds yet, to edit and
  pass as `--zone-map`. [docs/zeek.md](docs/zeek.md).
- The **OT overview is useful right after an import**. It opens with *Exposure of the controllers*: flows into
  control zones, how many nobody decided on although they write, are remote access or come from outside, and
  external zones. Next to it, *Next steps* lists what to add next in the order that clears the most findings:
  devices, verdicts on the flows into control zones, owner and levels per zone, conduits, then risk assessments
  and requirement statuses. Each step shows how many objects are left and links to them for a bulk edit. Headline
  cards show "—" instead of 0 when nothing is assessed yet, and external zones no longer appear under "No target
  level" or "Without an approved assessment" (the checks have skipped them since 0.5.0). The REST overview has
  `exposure` and `next_steps`. New zone and conduit filters `has_sl_achieved` and `has_accountable`.

- **Unknown-host import files** (`--unknown-import`) keep what the source knew and load for a second plant:
  devices are named `unknown-<address>-<site slug>` (NetBox's interface and IP address import finds a device by
  name across all sites, so a second plant on the same addresses matched the first plant's devices); the
  source's role goes into the description, and into `role` when NetBox has a device role of that name; the
  Purdue level into a new `cf_ot_purdue_level` column; new `--unknown-role` and `--unknown-device-type`
  defaults; addresses the VRF already holds are left out of the IP address file and listed with the advice to
  give each plant its own VRF. The output says the columns take names, not slugs. The unknown-host report has
  `role` and `purdue_level` columns. README: a first import of your own capture, one VRF per plant.

- **Port scans no longer become a wall of ports.** A TCP connection that was answered but carried no data is a
  probe, not traffic. A source that tried 100 or more TCP ports, with data on at most a fifth, is reported as a
  port scan in the import output and in the evidence of the flows between the two zones; what it reached with
  only conn.log to show for it becomes one *port scan* request per destination without ports, while its
  protocol-log requests (S7, Modbus) stay. 4SICS day 2: the visitors' network went from eight flows (one with 55
  ports) to three. The observation format has an optional `scans` summary field. Lists and the access map show
  at most six ports of a flow and the total ("TCP/80, ... (58 ports)"); the flow page shows them all.

- The import **says when the zone map's type differs** from an existing zone's type in NetBox (it keeps
  NetBox's; before, the difference passed silently).

- **Re-imports report moved assets**: when the input puts a device or VM in another zone, the import lists the
  zones it is still in, and the new `--move` drops the old membership (a parent or sub-zone does not count).
- A **split says what will not hold**: hosts of a split part that are not devices in NetBox yet (their levels
  live only in this input), and a split zone left without members, with the prefix it still holds.

### Bug fixes

- An **unscoped prefix was linked into the zones of several sites**: the 4SICS imports into three sites linked
  the same global 10.10.10.0/24 and 192.168.x prefixes to a zone of each. A prefix that already sits in a zone of
  another site is no longer linked; the import says so and suggests scoping it or a VRF per plant.
- The **access map diagram cut off its lowest level** (the controllers) when the drawing was taller than the
  view, and *Fit* did nothing: it only fitted the width. The diagram now fits width and height on first load
  (no smaller than readable), and *Fit* always shows the whole drawing.
- The **Zeek import's memory grew with the logs**: every record of every log was held in memory before it was
  aggregated (1.15 GB for a 55 MB conn.log; day 2 of the 4SICS capture was killed at a 900 MB cap). The logs are
  now read record by record and only the aggregates are kept: the same day 2 adds about 1 MB to NetBox's own
  memory and takes 7 s.

- A **risk assessment saved through the REST API** or a script got no risk level from its likelihood and impact:
  the matrix only filled the level in on the form. The level is now taken from the matrix on every save.
- The **flow form joined zones of two sites** without a word: the zone lists showed every site's zones without
  the site ("Control room" twice). Zone and conduit choices on the flow and risk assessment forms now name their
  site, a *Site* picker narrows the lists (preselected when editing), and a flow between zones of two different
  sites is refused unless one of them is a DMZ, enterprise or external zone. The new check
  `flow-between-sites` (error) finds such flows saved before. The REST API's brief zone and conduit
  representations now include `site`.

## 0.5.0 (2026-11-14)

Minor release: the OT overview per site, an access map that stays readable on a large plant, a risk matrix and
the IEC 62443-3-2 steps on risk assessments, exposure checks that put undecided writes into control zones first,
and importer fixes found on a real ICS capture. No breaking changes; upgrading from 0.4.x runs one migration
(`0005_risk_matrix`, four optional fields). The plugin now ships static files: run `manage.py collectstatic`
after upgrading (NetBox's `upgrade.sh` does).

### New features

- Visual aids on a risk assessment ([#33](https://github.com/Packetflow-be/netbox-ot/pull/33)): a **risk
  matrix** (likelihood by impact) that shows where the unmitigated and the residual risk sit and where the
  tolerable risk ends, and the **steps** of an IEC 62443-3-2 assessment with the one the assessment is at and
  what is still missing. Likelihood and impact are four new optional fields (migration `0005_risk_matrix`, which
  only adds them); with both given the matrix gives the risk level. The matrix is the organisation's own: the
  `risk_matrix` setting replaces the default 5 x 5. The list of risk assessments has a *Step* column and the
  API a read-only `current_step`. Assessments without likelihood and impact stay valid and show their levels
  on a plain scale. [docs/risk-assessments.md](docs/risk-assessments.md).

### Enhancements

- **OT overview**: a tab on every site with zones that shows where the site stands. A radar chart of achieved
  against target security level per foundational requirement (for the site, the weakest zone per foundational
  requirement; or one zone), a table of every
  zone and conduit sorted by how far below target it is, requirement statuses per foundational requirement,
  risk before and after countermeasures with what is still above the tolerable risk, and the number of check
  findings. Printable, drawn on the server without scripts, and also as `GET overview/?site_id=<id>` in the
  API. No migrations ([#31](https://github.com/Packetflow-be/netbox-ot/pull/31)).
- The access map stays readable on a large plant ([#32](https://github.com/Packetflow-be/netbox-ot/pull/32)).
  The diagram is a layered layout: a Purdue level with many zones wraps into several rows, arrows that skip a
  level run between the zones instead of behind them, zones are ordered to keep crossings down, and an arrow
  shows how many flows it carries per verdict. New filters on the page (verdict, zone with its neighbours,
  protocol, connection model, remote access, sub-zones drawn inside their parent zone) apply to the diagram
  and the table and are URL parameters. With the plugin's own script (no library, nothing loaded from
  elsewhere): zoom, drag, highlighting of a zone or an arrow, a panel with its flows, and an SVG download. The
  diagram is still server-rendered SVG, so it prints and works without JavaScript. Zones without flows are
  left out unless asked for, and the page for all sites no longer draws the zones of every site in one
  picture. The plugin now ships static files: run `manage.py collectstatic` after upgrading (NetBox's
  `upgrade.sh` does).
- **Exposure first** ([#34](https://github.com/Packetflow-be/netbox-ot/pull/34)). Two new checks:
  `undecided-into-control` (error) for an undecided flow into a control zone (level 0-1 or safety) that writes,
  controls or programs it, is remote access or comes from a DMZ, enterprise or external zone, and
  `outside-into-control` (warning) for a flow allowed straight from such a zone into a control zone. Both lead
  *Needs attention* on the access map and are flow filters of the same names. Within a verdict the access map
  lists flows that change the controllers from outside first, and the diagram draws an arrow heavy when a flow
  on it writes, controls or programs. The checks for a missing SL-T, accountable person or risk assessment leave
  external zones out: a supplier or the internet is outside the system under consideration.
- `ot_demo --large` creates a second demo plant of 35 zones and about 200 flows on its own site, to try the
  plugin at the size of a real plant ([#32](https://github.com/Packetflow-be/netbox-ot/pull/32)).

### Bug fixes

Found by importing a real ICS lab capture (the public 4SICS captures) with Zeek and the CISA ICSNPP parsers
([#34](https://github.com/Packetflow-be/netbox-ot/pull/34)):

- **Traffic inside a zone is no longer lost without a word.** The import reports the industrial requests
  between assets of the same zone, with the writes and who sent them, and how to put them on the access map.
  `--split` says why a zone was not split.
- **`--split` works on Zeek logs.** The level on an address line of the zone map is that asset's level, and an
  asset without one takes the level its NetBox device or VM already has; before, every asset of a zone got the
  zone's level, so a zone never counted as mixed.
- **A zone's level is no longer written onto its devices.** The level on a network line of the zone map is the
  zone's own (summary.json `zones` takes an optional `purdue_level` for the same); the import sets a device's
  or VM's level only from that asset's own level. Before, an HMI in a level 1 cell became a level 1 device.
- A flow's evidence starts with that flow's own request count. The connection count of the zone pair (every
  protocol between the two zones) is a labelled second line; before, it opened every flow of the pair, so all
  of them showed the same number.
- The OT overview's radar no longer averages security levels over zones (it showed levels like 1.5, which do
  not exist, and hid a weak zone behind strong ones). For the site, each foundational requirement shows the
  weakest zone: the one furthest below its target. The chart names those zones, and the API gives each axis
  its `zone`.
- ICMP in Zeek's conn log no longer turns into TCP ports: Zeek writes an ICMP message's type and code in the
  port fields, which became flows and services on `tcp/3` or `tcp/14`.

### Documentation

- netbox-branching is marked as not recommended alongside netbox-ot: it works, but every release with a
  migration leaves the branches with pending migrations, so they have to be rebuilt after each upgrade.
  `ot_import --dry-run`, a separate site or a test NetBox are the lighter ways to try an import
  ([#34](https://github.com/Packetflow-be/netbox-ot/pull/34)).

- The menu and the panel on device and VM pages are called *OT* in the README and the docs, as in the plugin
  since 0.3.0; the API and installation pages list the system requirement objects of 0.4.0 and the firmware
  version custom field ([#30](https://github.com/Packetflow-be/netbox-ot/pull/30)).

## 0.4.1 (2026-11-12)

Patch release: one enhancement to the demo plant. No migrations.

### Enhancements

- `ot_demo` gives the demo controllers, operator panel, gateway and firewall a firmware version (custom field
  `ot_firmware_version`), so the demo shows the field filled in and one PLC a release behind the other. Setting
  them afterwards through the API fails on a NetBox whose custom validators reject the demo's device names.
- README: the logo sits in the title line ([#27](https://github.com/Packetflow-be/netbox-ot/pull/27)).

## 0.4.0 (2026-11-12)

Minor release: system requirements (IEC 62443-3-3) with their status per zone or conduit, connection models on
flows (OPC UA Reverse Connect, MQTT and other brokers, PubSub) and working in a netbox-branching branch. No
breaking changes; upgrading from 0.3.0 runs three migrations (`0002` to `0004`) that only add tables and fields.

### New features

- Working in a branch of the [netbox-branching](https://github.com/netboxlabs/netbox-branching) plugin (optional,
  separately licensed) ([#9](https://github.com/Packetflow-be/netbox-ot/issues/9)): `--branch NAME` on `ot_demo`,
  `ot_import`, `ot_check` and `ot_rules`; *OT > Settings* (with netbox-branching only) with a default branch for
  `ot_import` and `ot_demo` (`--main` forces main) and a guard that refuses imports into main;
  [docs/branching.md](docs/branching.md). CI runs the suite once more with netbox-branching installed.
- `ot_demo` writes to the change log (under `--user`, default the first superuser), like the importer, so demo
  data made in a branch shows in its diff and is carried over by a merge.
- Migration `0002_plugin_settings` (one table for the settings).
- Connection models on flows ([#11](https://github.com/Packetflow-be/netbox-ot/issues/11)): client/server
  (default), reverse connect (OPC UA Reverse Connect), through a broker (MQTT, Sparkplug B, OPC UA PubSub over a
  broker) with a broker zone and topics, and published without a session (OPC UA PubSub over UDP). The access map
  draws flows without an inbound connection dotted and lists them under *Needs attention*; firewall rules follow
  the connection (reverse connect from the destination zone, a broker as two rules into its zone, new column
  `connection`); register, REST API, GraphQL, filters and CSV import carry the new fields; new check
  `brokered-write-without-topics`; the demo plant has one flow of each new kind. Migration `0003_flow_connection`.
- System requirements (IEC 62443-3-3) and their status per zone or conduit
  ([#6](https://github.com/Packetflow-be/netbox-ot/issues/6)): met, met by a compensating countermeasure, not
  met, not applicable, with countermeasure, evidence, risk assessment, assessed by and on. The plugin ships
  identifiers and foundational requirements only; `ot_requirements` loads them and, with `--csv`, the
  enhancements, levels and wording from the user's own licensed copy. Checks `requirements-without-status` and
  `requirement-not-met-for-sl-a`; a requirements table and CSV in the zone register; REST API, GraphQL;
  [docs/requirements.md](docs/requirements.md). Migration `0004_system_requirements`.
- Importer: observation files take `connection`, `broker` and `topic` per request. From Zeek logs an OPC UA Reverse
  Connect (ReverseHello) is imported the right way round (it pointed out of the PLC's zone), and MQTT
  publish/subscribe through a broker (`mqtt_publish`, `mqtt_subscribe`) becomes flows through the broker from
  publisher to subscriber, with their topics; Sparkplug B commands count as write.

## 0.3.0 (2026-11-12)

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

### New features

- Companion plugins: CI runs the suite beside netbox-lifecycle 1.1.11 and netbox-inventory 2.7.1, the tested
  bundle documented in [docs/companions.md](docs/companions.md) ([#15](https://github.com/Packetflow-be/netbox-ot/issues/15)).
- End of support per device when netbox-lifecycle is installed: the earliest end-of-security (else
  end-of-support) date of the device type and its installed modules' types, in the device panel and the zone
  register; checks `end-of-support` (warning) and `end-of-support-ahead` (info) for zones with SL-T 2 or more
  ([#16](https://github.com/Packetflow-be/netbox-ot/issues/16)).
- Custom field *Firmware version* (`ot_firmware_version`) on devices and modules.

### Enhancements

- NetBox refuses to start with both `netbox_iec62443` and `netbox_ot` in `PLUGINS`, with a message that says
  what to do.
- CI upgrades a real netbox-iec62443 0.2.0 installation with the demo plant to this version on every run.
- The takeover also works inside [netbox-branching](https://github.com/netboxlabs/netbox-branching) branches:
  migrating a branch renames its copy of the tables and its own custom field values
  ([#21](https://github.com/Packetflow-be/netbox-ot/pull/21)).

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
