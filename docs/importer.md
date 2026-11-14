# Importer: Zeek logs and observation files

```
manage.py ot_import <dir> --site <slug> [--vrf <name or RD>] [--user <name>] [--dry-run]
    [--format auto|zeek|observations] [--zone-map CSV] [--suggest-zone-map CSV]
    [--unknown-report CSV] [--unknown-import DIR [--unknown-role NAME] [--unknown-device-type MODEL]]
    [--outside-zone NAME] [--split ZONE ... | --split-all]
```

```bash
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py ot_import ./observations --site <site-slug> --dry-run
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py ot_import ./observations --site <site-slug>
```

Reads either a directory of **Zeek logs** (`conn.log` plus the protocol logs of Zeek and the CISA ICSNPP
parsers, TSV or JSON, as Zeek or Malcolm write them; see [zeek.md](zeek.md)), or **observation files** in the
format described in [import-format.md](import-format.md) (`assets.json`, `flows.json`, optionally
`summary.json`) that any other tool or a spreadsheet can produce. For Zeek logs the zones come from NetBox
(zone prefixes and members), plus an optional `--zone-map` for zones NetBox does not have yet.

The plugin does not capture traffic or run Zeek itself: it reads what a sensor already wrote.

## What an import creates

One import covers **one site and one routing domain**. The same machine network (say 192.168.0.0/24
behind every OEM machine) is normal in OT, so the importer only matches devices, VMs and prefixes at
`--site` and in `--vrf` (default: the global table). Import captures from different VRFs separately.
It creates:

- a zone per zone name in the input, with the assets found there (matched to NetBox devices/VMs by
  primary IPv4 at the site and in the VRF; an address that matches more than one is skipped and
  reported), Purdue level = the lowest level among its assets, type as declared in the input or from
  its level (addresses outside the input go to an external zone);
- links to the prefixes NetBox already has for those assets (the most specific one, not a
  container). It never creates prefixes, and it leaves a prefix unlinked when it holds assets of
  more than one zone;
- a flow per source zone, destination zone and protocol seen, with the ports the input gives (none
  are assumed), first/last seen, and the requests as evidence. Every request is classified as read,
  write, control or program by an explicit table per protocol (`netbox_ot/importers/functions.py`);
  the senders of write, control and program requests are listed in the evidence, and *remote access* is
  set when an asset marked `remote_access` in the input sent requests across. A flow is put in a conduit
  only when exactly one conduit joins both of its zones;
- industrial services, and for a server whose port is known, a link to a NetBox application service
  with that port (found or created on the asset);
- the Purdue level custom field on the matched assets (only where it is still empty).

## Hosts NetBox does not know

Every import ends with the **observed hosts that match no device or VM** in NetBox at the site, hosts inside
a zone first, and `--unknown-report FILE.csv` writes them all with what was seen of them: finding these is
the point of passive discovery. Flows out of an external zone are marked as remote access.

The importer never creates devices: a capture shows an address and what it talks, not what the machine is.
`--unknown-import DIR` writes the unknown hosts inside a zone of the plant (not those in an external zone)
as three files for NetBox's own bulk import: `1-devices.csv`, `2-interfaces.csv` and `3-ip-addresses.csv`.
Import the three in that order (Devices, Interfaces, IP addresses > Import) and run the import again: the
new devices now get their zone, Purdue level and services.

- The devices are named `unknown-<address>-<site slug>`, so a second plant on the same addresses gets other
  names (NetBox's interface and IP address import finds a device by name across all sites). Rename them in
  NetBox afterwards.
- `role`, `manufacturer` and `device_type` take **names as NetBox shows them**, not slugs. What the source
  called a host (assets.json `role`, e.g. "PLC (ControlLogix)") goes into the description, and into `role`
  when NetBox has a device role of that exact name. Its Purdue level goes into `cf_ot_purdue_level`.
- `--unknown-role NAME` and `--unknown-device-type MODEL` fill in the rest, e.g. a role "Unknown" and a
  placeholder device type to replace later, so dozens of rows need not be filled in by hand.
- Addresses NetBox already holds in the import's VRF are left out of `3-ip-addresses.csv` and listed: NetBox
  refuses the whole file over the first duplicate in the global table.

**One VRF per plant.** Plants reuse the same private ranges (192.168.0.0/24, 10.10.10.0/24). Give each plant
its own VRF in NetBox and import with `--vrf`: devices, prefixes and addresses are then matched within that
plant only, and the unknown-host files do not collide with another plant's addresses.

## Options

- `--vrf NAME_OR_RD` matches devices, VMs and prefixes in this VRF instead of the global table.
- `--outside-zone NAME` names the zone for addresses not in assets.json (default `Outside`).
- `--split ZONE` splits a zone that mixes Purdue bands into one zone per band, named
  `ZONE (control)` (levels 0-1), `ZONE (supervisory)` (2) and `ZONE (operations)` (3 and up), so the
  paths between them become flows (e.g. an engineering laptop writing to a PLC in the same cell).
  Traffic counted for the whole zone goes to the part its OT requests point at, else to the most
  critical part. `--split-all` does this for every mixed zone. A split needs the assets' own levels: from
  assets.json, an address line in the zone map, or the level the NetBox device or VM already has. When a zone
  cannot be split, the import says why.
- `--dry-run` shows what would change and writes nothing.
- `--user NAME` records the changes in the change log under that user (default: the first superuser).

## Traffic inside a zone

Flows run between zones, so requests between two assets of the same zone are not flows and not on the access
map. The import still counts the industrial ones and reports them per zone, with the write, control and
program requests and who sent them, and how to put them on the map:

```
Industrial traffic inside a zone (flows run between zones, so this is not on the access map):
  S7 cell: 105217 request(s) from 3 host(s), 72 of them write/control/program (from 10.10.10.30)
    its assets are at Purdue levels 1, 2: --split "S7 cell" turns this traffic into flows
```

## Purdue levels

An asset's level comes from the input (assets.json `purdue_level`, an address line in the zone map) or, when
the input gives none, from the level its NetBox device or VM already has. The import sets a level on a device
or VM only when it has none yet, and only from an asset's own level, never from its zone's.

## Re-running

Re-running adds ports and access classes, widens first/last seen and refreshes evidence, but never
touches a flow's verdict, conduit or hops, or a level someone set.

## Other sources

The importer is split in two: `build_plan()` turns observations into an `ImportPlan` (zones with member IPs,
flows with evidence, services, per-asset levels, observed hosts), and `apply_plan()` writes any plan to
NetBox, resolving addresses to devices, VMs and prefixes within the site and VRF. The Zeek adapter
(`importers/zeek.py`) only turns logs into observations; another source needs the same and nothing else.
