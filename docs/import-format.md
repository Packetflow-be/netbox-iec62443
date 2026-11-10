# Import format (observation files)

`manage.py iec62443_import <dir> --site <slug>` reads a directory with two or three JSON files. They
describe what was seen on an OT network; any tool can write them: a script over Zeek (with the CISA
ICSNPP parsers) or Malcolm logs, an export from an asset-discovery tool, or a spreadsheet you convert.
The importer matches assets to existing NetBox devices and VMs by primary IPv4 address, only at the
import's site and in its VRF (`--vrf`, default the global table); it does not create devices or
prefixes. One directory describes one site and one routing domain.

## assets.json (required)

A list of assets. One object per IP address.

| Field | Required | Meaning |
|---|---|---|
| `ip` | yes | IPv4 address; matched to a device's or VM's primary IPv4 |
| `zone` | yes | Zone name. Group assets however your site works: per cell, line, VLAN or subnet |
| `purdue_level` | no | 0, 1, 2, 3, 3.5, 4 or 5 (number or null). Sets the asset's Purdue level if still empty |
| `role` | no | Free text, e.g. "PLC", "HMI", "Supplier 4G gateway". Only used as a label |
| `remote_access` | no | `true` if the asset is an entry point from outside the site: a supplier's 4G router, a VPN gateway, a remote-desktop or jump host. Conduits that carry its OT requests are marked as remote access. Default `false` |
| `services` | no | Protocols the source identified on the asset by dissecting its traffic or configuration, as server: list of `{"proto": "iec-61850-mms", "port": 102}` (`port` optional). Each becomes a server service |
| `open_ports` | no | List of listening TCP/UDP ports. A port alone does not identify a protocol (102 is S7comm, S7comm-plus or IEC 61850 MMS), so it creates no service; well-known OT ports that no identified service explains are listed in the import output |

## flows.json (required, may be `[]`)

OT requests between assets: one object per source, destination, protocol and function.

| Field | Required | Meaning |
|---|---|---|
| `src`, `dst` | yes | IPv4 addresses. An address not in assets.json belongs to the outside zone |
| `proto` | yes | Protocol name as Zeek/ICSNPP or tshark write it (`S7comm`, `Modbus`, `ENIP`, `DNP3`, `BACnet`, `OPCUA`, `IEC104`, `PROFINET`, `MQTT`) or one of the plugin's protocol values (`modbus-tcp`, `s7comm`, `ethernet-ip`, ...) |
| `func` | no | Function as the tool names it, e.g. "Read Variable", "WRITE_SINGLE_COIL", "Force Single Coil", "PLC Stop", "DIRECT_OPERATE", "C_SC_NA_1". Classified as read, write, control, program or other by an explicit table per protocol (`importers/functions.py`); a name not in the table stays *unclassified* |
| `access` | no | The class itself, if the tool knows it: `read`, `write`, `control` (commands, run/stop, reset, restart), `program` (logic, firmware or file download) or `other`. Overrides the table. Senders of write, control and program requests are shown as *via* |
| `count` | no | Number of requests (default 1) |

## summary.json (optional)

| Field | Meaning |
|---|---|
| `zone_pairs` | List of `{"from": zone, "to": zone, "count": n}`: all traffic between zones, not only OT requests. Pairs that only appear here still become conduits. A zone name not in assets.json means the outside zone |
| `captures` | List of capture names, quoted in the evidence |
| `hours` | Capture duration in hours, quoted in the evidence |

## Example

```
assets.json   [{"ip": "10.10.10.10", "zone": "Cell A", "purdue_level": 1, "role": "PLC", "open_ports": [102],
                "services": [{"proto": "s7comm", "port": 102}]},
               {"ip": "10.10.10.20", "zone": "Cell A", "purdue_level": 2, "role": "HMI"},
               {"ip": "10.20.0.15",  "zone": "Office", "purdue_level": 4}]
flows.json    [{"src": "10.10.10.20", "dst": "10.10.10.10", "proto": "S7comm", "func": "Read Variable", "count": 5500}]
summary.json  {"zone_pairs": [{"from": "Office", "to": "Cell A", "count": 300}]}
```

`--split "Cell A"` then gives zones *Cell A (control)* and *Cell A (supervisory)* with the HMI's S7comm
path as a conduit between them, and a conduit *Office -> Cell A (control)* for the office traffic.
