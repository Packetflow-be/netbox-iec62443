# Import format (observation files)

`manage.py ot_import <dir> --site <slug>` reads a directory with two or three JSON files. They
describe what was seen on an OT network; any tool can write them: an export from an asset-discovery tool, a
script over another sensor's output, or a spreadsheet you convert. Zeek logs need no conversion: the importer
reads them directly (see [zeek.md](zeek.md)).
The importer matches assets to existing NetBox devices and VMs by primary IPv4 address, only at the
import's site and in its VRF (`--vrf`, default the global table); it does not create devices or
prefixes. One directory describes one site and one routing domain.

Times are ISO 8601 (`2026-11-03T14:05:00Z`); a time without a zone is taken in NetBox's time zone.

## assets.json (required)

A list of assets. One object per IP address.

| Field | Required | Meaning |
|---|---|---|
| `ip` | yes | IPv4 address; matched to a device's or VM's primary IPv4 |
| `zone` | yes | Zone name. Group assets however your site works: per cell, line, VLAN or subnet |
| `purdue_level` | no | 0, 1, 2, 3, 3.5, 4 or 5 (number or null). Sets the asset's Purdue level if still empty |
| `role` | no | Free text, e.g. "PLC", "HMI", "Supplier 4G gateway". Only used as a label |
| `remote_access` | no | `true` if the asset is an entry point from outside the site: a supplier's 4G router, a VPN gateway, a remote-desktop or jump host. Flows that carry its requests are marked as remote access. Default `false` |
| `services` | no | Protocols the source identified on the asset by dissecting its traffic or configuration, as server: list of `{"proto": "iec-61850-mms", "port": 102, "transport": "tcp"}` (`port` and `transport` optional). Each becomes a server service; with a port, also a NetBox application service |
| `open_ports` | no | List of listening TCP/UDP ports. A port alone does not identify a protocol (102 is S7comm, S7comm-plus or IEC 61850 MMS), so it creates no service; well-known OT ports that no identified service explains are listed in the import output |

## flows.json (required, may be `[]`)

Requests between assets: one object per source, destination, protocol and function (and port, if you
have it).

| Field | Required | Meaning |
|---|---|---|
| `src`, `dst` | yes | IPv4 addresses. An address not in assets.json belongs to the outside zone |
| `proto` | yes | Protocol name as Zeek/ICSNPP or tshark write it (`S7comm`, `Modbus`, `ENIP`, `DNP3`, `BACnet`, `OPCUA`, `IEC104`, `MMS`, `PROFINET`, `MQTT`, `RDP`, `SSH`, ...) or one of the plugin's protocol values (`modbus-tcp`, `s7comm`, `ethernet-ip`, `rdp`, ...). An unknown name still makes a flow, without a protocol |
| `port` | no | Destination port (the responder's). Becomes the flow's port and, for an industrial protocol, the server's application service port. Without it no port is assumed |
| `transport` | no | `tcp` or `udp` for `port`. Default: the protocol's usual transport (UDP for BACnet/IP, KNXnet/IP, Omron FINS, PROFINET CM, DNS, NTP, SNMP, Syslog, IPsec, OpenVPN, WireGuard; TCP otherwise) |
| `func` | no | Function as the tool names it, e.g. "Read Variable", "WRITE_SINGLE_COIL", "Force Single Coil", "PLC Stop", "DIRECT_OPERATE", "C_SC_NA_1". Classified as read, write, control, program or other by an explicit table per protocol (`importers/functions.py`); a name not in the table stays *unclassified* |
| `access` | no | The class itself, if the tool knows it: `read`, `write`, `control` (commands, run/stop, reset, restart), `program` (logic, firmware or file download) or `other`. Overrides the table. Senders of write, control and program requests are listed in the flow's evidence |
| `count` | no | Number of requests (default 1) |
| `first_seen`, `last_seen` | no | When these requests were seen. Default: summary.json `start` and `end` |

## summary.json (optional)

| Field | Meaning |
|---|---|
| `zone_pairs` | List of `{"from": zone, "to": zone, "count": n}`: all traffic between zones, not only identified requests. A pair with no identified request still becomes a flow, without a protocol. A zone name not in assets.json means the outside zone |
| `zones` | List of `{"name": zone, "type": type}` with the type of zones the importer creates: `ot`, `safety`, `dmz`, `enterprise` or `external`. Default: 3.5 is a DMZ, 4 and 5 enterprise, other levels OT, the outside zone external. Existing zones keep their type |
| `captures` | List of capture names, quoted in the evidence |
| `hours` | Capture duration in hours, quoted in the evidence |
| `start`, `end` | The capture window; the first/last seen of flows that give none |

## Example

```
assets.json   [{"ip": "10.10.10.10", "zone": "Cell A", "purdue_level": 1, "role": "PLC", "open_ports": [102],
                "services": [{"proto": "s7comm", "port": 102}]},
               {"ip": "10.10.10.20", "zone": "Cell A", "purdue_level": 2, "role": "HMI"},
               {"ip": "10.20.0.15",  "zone": "Office", "purdue_level": 4},
               {"ip": "10.99.0.5",   "zone": "Supplier", "role": "4G router", "remote_access": true}]
flows.json    [{"src": "10.10.10.20", "dst": "10.10.10.10", "proto": "S7comm", "port": 102,
                "func": "Read Variable", "count": 5500},
               {"src": "10.99.0.5", "dst": "10.10.10.10", "proto": "S7comm", "port": 102, "func": "PLC Stop"}]
summary.json  {"zone_pairs": [{"from": "Office", "to": "Cell A", "count": 300}],
               "zones": [{"name": "Supplier", "type": "external"}],
               "start": "2026-11-03T08:00:00Z", "end": "2026-11-03T16:00:00Z"}
```

`--split "Cell A"` then gives zones *Cell A (control)* and *Cell A (supervisory)*, a flow *Cell A
(supervisory) -> Cell A (control) S7comm* (read, tcp/102) for the HMI, a remote-access flow *Supplier ->
Cell A (control) S7comm* (control) for the 4G router, and a flow *Office -> Cell A (control)
(unidentified)* for the office traffic.
