# netbox-iec62443

A NetBox plugin for OT networks: **IEC 62443 zones and conduits**, **Purdue levels** on devices and
virtual machines, and an **access map**: every known path into the controller zones, with an
"allowed?" verdict per path.

It was written for floor walk-throughs of small factories (PLCs, HMIs, machine PCs, supplier remote
access over 4G routers, TeamViewer or VPN), where the deliverable is that access map. It works just as
well as a plain zones-and-conduits register next to your existing NetBox inventory.

Status: early development (0.1.0.dev0), tested on NetBox 4.7.4 only.

![Access map tab on a site](docs/access-map.png)

![A zone with its conduits, devices and prefixes](docs/zone.png)

## What you get

- **Zone**: name, slug, site, tenant, Purdue level (0, 1, 2, 3, 3.5 DMZ, 4, 5), security level
  target (SL-T 0-4), member devices, virtual machines and prefixes, description, tags, comments.
- **Conduit**: source zone, destination zone, direction (one-way / two-way), **allowed** (yes / no /
  unknown), protocols/ports (free text), remote access flag, via (free text, e.g. "4G router of
  supplier X"), evidence, description, tags, comments.
- **Purdue level on devices and VMs** as a custom field (`iec62443_purdue_level`, group "IEC 62443").
- **Access map**: per site, all conduits into zones at Purdue level <= 2 (selectable), sorted with
  the not-allowed paths first, plus a small server-rendered diagram. Available as an "Access map" tab
  on the site page and under *IEC 62443 > Access map*.
- An **IEC 62443 panel on device and VM pages**: the asset's Purdue level, its zones and their conduits.
- The usual NetBox plumbing: list/detail/edit/delete, bulk import/edit/delete, filters, global search,
  change log, journal, REST API (`/api/plugins/iec62443/zones/`, `/conduits/`), GraphQL
  (`iec62443_zone_list`, `iec62443_conduit_list`).
- An **importer** for passive-capture analysis output (see below).

## Install

```
pip install netbox-iec62443          # not on PyPI yet: pip install /path/to/netbox-iec62443
```

`configuration.py`:

```python
PLUGINS = ["netbox_iec62443"]
PLUGINS_CONFIG = {
    "netbox_iec62443": {
        "create_custom_fields": True,     # create the Purdue level custom field after migrate
        "access_map_max_level": "2",      # default level filter of the access map
    },
}
```

Then `manage.py migrate`. With [netbox-docker](https://github.com/netbox-community/netbox-docker),
add the package to `plugin_requirements.txt` and build a custom image as described in its wiki; for
development you can mount the source and set `PYTHONPATH` instead (see `docs/development.md`).

Permissions: users who view conduits also need view permission on zones (a conduit shows its zones).

## Design choices

- **Zone members are plain many-to-many fields** (`devices`, `virtual_machines`, `prefixes`) rather
  than a generic assignment model. That is the simplest thing NetBox supports end to end (forms,
  REST API, GraphQL, change log) and it lets an asset sit in more than one zone when reality is
  messy. The plugin does not enforce one zone per asset; the device panel shows all of them.
- **Purdue level on devices/VMs is a custom field**, created by the plugin after `migrate` if it does
  not exist (never overwritten afterwards, so you may relabel it). Nothing is added to core tables,
  and you get filtering, bulk edit and CSV import of that field for free. Set
  `create_custom_fields: False` to manage it yourself.
- **Purdue level values are strings** ("0" ... "5", "3.5"), so the DMZ level fits; "at or below
  level N" is computed from the choice list.
- **A conduit connects two different zones** (IEC 62443-3-2). Traffic inside a zone is not a
  conduit; if a path inside a zone matters (an engineering laptop writing to a PLC in the same cell),
  that usually means the zone should be split.
- **"Allowed" defaults to unknown.** Tools fill in evidence; a person decides yes or no.
- Zone names and slugs are unique per site (and globally for zones without a site).

## Importer: passive capture analysis

```
manage.py iec62443_import_vloerscan <dir> --site <slug> [--user <name>] [--dry-run]
    [--rename "OLD=NEW" ...] [--outside-zone NAME] [--split ZONE ... | --split-all]
```

Reads `assets.json`, `flows.json` and `summary.json` as written by the Vloerscan prototype
(Zeek + CISA ICSNPP parsers + tshark, summarised per /24 segment) and creates:

- a zone per segment name, with the segment's /24 prefix and the assets found there (matched to
  NetBox devices/VMs by primary IPv4), Purdue level = the lowest level among its assets;
- a conduit per directed zone pair seen talking, with the OT protocols/functions that crossed it,
  the connection counts as evidence, and *via* / *remote access* filled in when a router in another
  zone writes into a controller;
- the Purdue level custom field on the matched assets (only where it is still empty).

Options:

- `--rename "OLD=NEW"` renames a zone from the input (repeatable), e.g. to translate segment names.
- `--outside-zone NAME` names the zone for addresses outside the scanned floor (default `Outside`).
- `--split ZONE` splits a zone that mixes Purdue bands into one zone per band, named
  `ZONE (control)` (levels 0-1), `ZONE (supervisory)` (2) and `ZONE (operations)` (3 and up), so the
  paths between them become conduits (e.g. an engineering laptop writing to a PLC in the same cell).
  Traffic counted for the whole zone goes to the part its OT requests point at, else to the most
  critical part. `--split-all` does this for every mixed zone.

Re-running refreshes evidence but never overwrites a conduit's "allowed" or a level someone set.
Changes are recorded in the change log under `--user` (default: the first superuser).

**Other sources (not built yet).** The importer is split in two: `build_plan()` turns input files
into an `ImportPlan` (zones with prefixes and member IPs, conduits with evidence, per-asset levels),
and `apply_plan()` writes any plan to NetBox. A Malcolm or plain Zeek importer only needs its own
`build_plan`: aggregate `conn.log` (and the ICSNPP protocol logs) by NetBox prefix or zone instead of
by /24, and reuse `apply_plan()` unchanged. Malcolm already creates devices and prefixes in NetBox, so
such an importer could start from Malcolm's NetBox data and only add zones and conduits.

## Language

The plugin is written in English and every user-facing string goes through Django's translation
functions, so it follows the language of the NetBox install (`LANGUAGE_CODE`, or each user's
language preference) as soon as a translation exists. No translations ship yet; they would go in
`netbox_iec62443/locale/<lang>/LC_MESSAGES/django.po` (`manage.py makemessages -l <lang>` in the
plugin directory).

## Development

Tests follow NetBox's own test classes (`APIViewTestCases`, `ViewTestCases`, filterset mixins) and run
inside a NetBox installation with the plugin enabled:

```
python manage.py test netbox_iec62443 --keepdb
```

Query-count baselines live in `netbox_iec62443/tests/query_counts.json` (re-record with
`UPDATE_QUERY_COUNTS=1`). See `docs/development.md` for the netbox-docker workflow.

## License

Apache License 2.0, see [LICENSE](LICENSE).
