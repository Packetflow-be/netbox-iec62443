# Companion plugins

netbox-ot needs no other plugin. For a full OT asset and lifecycle register it is meant to run beside two
mature community plugins, which it reads when they are installed and ignores when they are not. Core NetBox
already holds the asset register itself: devices, modules (a PLC's CPU and I/O cards), serial numbers, sites,
locations, racks, image attachments and journal entries.

| Need | Plugin | Licence | What netbox-ot does with it |
|---|---|---|---|
| End-of-sale, end-of-support and end-of-security dates; support contracts; licences | [netbox-lifecycle](https://github.com/DanSheps/netbox-lifecycle) | Apache-2.0 | End of support per device in the asset panel and the zone register; checks for devices past or near their end of support in zones with SL-T 2 or more |
| Spare parts, storage locations, purchases and deliveries | [netbox-inventory](https://github.com/ArnesSI/netbox-inventory) | MIT | Nothing yet: it runs beside netbox-ot (tested together) |

## The tested bundle

CI runs the full test suite beside these versions on every change (job *NetBox latest-4.7 + companion
plugins*). Install exactly these with this release of netbox-ot:

| netbox-ot | NetBox | netbox-lifecycle | netbox-inventory |
|---|---|---|---|
| 0.3.x | 4.7 | 1.1.11 | 2.7.1 |

The pins live in [`.github/ci/companions.txt`](../.github/ci/companions.txt). Newer releases of the
companions usually work too; the table says what was tested.

## Installing

Add the packages to `local_requirements.txt` (or netbox-docker's `plugin_requirements.txt`) and the apps to
`PLUGINS`, then migrate and restart as for netbox-ot itself ([installation](installation.md)):

```text
netbox-ot
netbox-lifecycle==1.1.11
netbox-inventory==2.7.1
```

```python
PLUGINS = ["netbox_ot", "netbox_lifecycle", "netbox_inventory"]
PLUGINS_CONFIG = {
    "netbox_ot": {},
    "netbox_lifecycle": {},
    "netbox_inventory": {},
}
```

## End of support

With netbox-lifecycle, add a *hardware lifecycle* (Lifecycle > Hardware) to a **device type** or a
**module type** with its end-of-support and, when the vendor publishes it, end-of-security date. netbox-ot then
works out per device:

- the earliest date of the device's own type and the module types of its installed modules, so a rack that is
  supported for years with a CPU module that is not shows the CPU's date;
- the end of security fixes when known, else the end of support;
- red when passed, orange within a year.

It shows in the device's *OT* panel and in the zone register (column *end of support*, devices past or within
a year of their date). Two consistency checks look at zones with an SL-T of 2 or more in any foundational
requirement:

| Check | Severity | |
|---|---|---|
| `end-of-support` | warning | a device in the zone is past its end of security fixes or support |
| `end-of-support-ahead` | info | a device in the zone reaches it within a year |

## Firmware versions

netbox-ot adds a text custom field **Firmware version** (`ot_firmware_version`) to devices and modules, shown
in the device's *OT* panel. Record the version that runs on the CPU module, not only on the chassis.
[netbox_slm](https://github.com/ICTU/netbox_slm) models software versions and installations in more detail,
but it attaches to devices only (not modules) and is not tested on NetBox 4.7 yet, so it is not part of the
bundle.

## Optional

These work beside netbox-ot without any integration: [netbox-documents](https://github.com/jasonyates/netbox-documents)
(drawings, manuals, certificates), [netbox-topology-views](https://github.com/netbox-community/netbox-topology-views)
and [netbox-qrcode](https://github.com/netbox-community/netbox-qrcode) (labels for cabinets and devices).

## A licence note

Some NetBox Labs plugins are not open source. [netbox-branching](https://github.com/netboxlabs/netbox-branching),
the [Diode](https://github.com/netboxlabs/diode-netbox-plugin) plugin and
[netbox-custom-objects](https://github.com/netboxlabs/netbox-custom-objects) are under the *NetBox Limited Use
License 1.0*: use inside your own organisation is allowed; redistributing them, or running them as a service
that competes with NetBox Labs, is not. netbox-ot works beside them but never depends on them; check the licence before you put them
in an image you hand out or a NetBox you run for others.
