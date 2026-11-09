# Import format (observation files)

`manage.py iec62443_import <dir> --site <slug>` reads a directory with two or three JSON files. They
describe what was seen on an OT network; any tool can write them: a script over Zeek (with the CISA
ICSNPP parsers) or Malcolm logs, an export from an asset-discovery tool, or a spreadsheet you convert.
The importer matches assets to existing NetBox devices and VMs by primary IPv4 address; it does not
create devices.

## assets.json (required)

A list of assets. One object per IP address.

| Field | Required | Meaning |
|---|---|---|
| `ip` | yes | IPv4 address; matched to a device's or VM's primary IPv4 |
| `zone` | yes | Zone name. Group assets however your site works: per cell, line, VLAN or subnet |
| `purdue_level` | no | 0, 1, 2, 3, 3.5, 4 or 5 (number or null). Sets the asset's Purdue level if still empty |
| `role` | no | Free text, e.g. "PLC", "HMI", "Router (supplier)". A role containing "router" marks a writer as remote access |
| `open_ports` | no | List of listening TCP/UDP ports. Well-known OT ports become server services (502 Modbus TCP, 102 S7comm, 44818 EtherNet/IP, 4840 OPC UA, 47808 BACnet/IP, 20000 DNP3, 2404 IEC 104, 5094 HART-IP, 9600 Omron FINS) |

## flows.json (required, may be `[]`)

OT requests between assets: one object per source, destination, protocol and function.

| Field | Required | Meaning |
|---|---|---|
| `src`, `dst` | yes | IPv4 addresses. An address not in assets.json belongs to the outside zone |
| `proto` | yes | Protocol name as Zeek/ICSNPP or tshark write it (`S7comm`, `Modbus`, `ENIP`, `DNP3`, `BACnet`, `OPCUA`, `IEC104`, `PROFINET`, `MQTT`) or one of the plugin's protocol values (`modbus-tcp`, `s7comm`, `ethernet-ip`, ...) |
| `func` | no | Function, e.g. "Read Variable", "Write Variable", "Write Single Register". A function containing "Write" marks the source as a writer (shown as *via*) |
| `count` | no | Number of requests (default 1) |

## summary.json (optional)

| Field | Meaning |
|---|---|
| `zone_pairs` | List of `{"from": zone, "to": zone, "count": n}`: all traffic between zones, not only OT requests. Pairs that only appear here still become conduits. A zone name not in assets.json means the outside zone |
| `captures` | List of capture names, quoted in the evidence |
| `hours` | Capture duration in hours, quoted in the evidence |

## Example

```
assets.json   [{"ip": "10.10.10.10", "zone": "Cell A", "purdue_level": 1, "role": "PLC", "open_ports": [102]},
               {"ip": "10.10.10.20", "zone": "Cell A", "purdue_level": 2, "role": "HMI"},
               {"ip": "10.20.0.15",  "zone": "Office", "purdue_level": 4}]
flows.json    [{"src": "10.10.10.20", "dst": "10.10.10.10", "proto": "S7comm", "func": "Read Variable", "count": 5500}]
summary.json  {"zone_pairs": [{"from": "Office", "to": "Cell A", "count": 300}]}
```

`--split "Cell A"` then gives zones *Cell A (control)* and *Cell A (supervisory)* with the HMI's S7comm
path as a conduit between them, and a conduit *Office -> Cell A (control)* for the office traffic.
