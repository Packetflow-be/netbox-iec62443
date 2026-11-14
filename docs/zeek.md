# Importing Zeek logs

`manage.py ot_import <dir> --site <slug>` reads a directory of Zeek logs directly, with or without the
[CISA ICSNPP](https://github.com/cisagov/ICSNPP) parsers, as Zeek or Malcolm write them. No converter needed.
The format is detected from the `conn` log; force it with `--format zeek`.

```bash
manage.py ot_import /captures/plant-a --site plant-a --suggest-zone-map zones.csv   # first visit: draft zone map
manage.py ot_import /captures/plant-a --site plant-a --zone-map zones.csv --dry-run
manage.py ot_import /captures/plant-a --site plant-a --zone-map zones.csv --unknown-report unknown.csv
```

Zeek TSV and JSON logs both work, plain or gzipped, rotated files included (`conn.00:00:00-01:00:00.log.gz`).
The logs are read record by record and never held in memory: what the import keeps is what it aggregates
(address pairs, protocols, functions, ports), so a week of plant traffic needs no more memory than an hour of it.

## Where addresses go: the zone map

Zeek knows addresses, not zones. The importer places each address in a zone from what NetBox already has
for the site, in the import's VRF (`--vrf`, default the global table):

1. the primary IPv4 address of a zone's member device or VM;
2. else the most specific prefix linked to a zone (a sub-zone wins over its parent).

Addresses in no zone go to the outside zone (`--outside-zone`, default `Outside`), which is created as an
external zone. For a first import, or for zones NetBox does not have yet (a supplier, an MSP), add a zone map:
a CSV file with `network or address, zone[, purdue_level][, type]` per line. Its lines win over NetBox.

On a first visit you may only know which networks exist. `--suggest-zone-map zones.csv` lists the networks the
conn log holds (per /24: hosts, connections and the services they answer) and writes a draft zone map with one
line per network that no zone holds yet, then stops without importing. Name the zones, give their level and
type, delete what you do not want, and import with `--zone-map zones.csv`. An import into a site without any
zone prints the same list before it stops.

```
Networks in the conn log (per /24):        (the public 4SICS ICS lab capture, day 2)
  10.10.10.0/24        3 host(s)    30350 connection(s), in no zone; serves tcp/102 (30336), s7comm (14)
  192.168.88.0/24     21 host(s)     7599 connection(s), in no zone; serves http (5808), ssl (367), tcp/80 (325), ...
  192.168.89.0/24      2 host(s)        2 connection(s), in no zone
  plus 4 public address(es): they go to the outside zone unless the zone map names them
```

```
network,zone,purdue_level,type
192.0.2.0/24,MSP,,external
10.10.30.0/24,Servers,3,
10.10.10.10,Cell A PLCs,1,
```

A zone named only in the zone map is created by the import, with the type given (`ot`, `safety`, `dmz`,
`enterprise`, `external`).

The Purdue level means two different things depending on the line:

- on a **network** line it is the **zone's** level (the zone's most critical one). It is not copied onto the
  assets in that network: a cell at level 1 also holds its HMI and engineering station.
- on an **address** line it is that **asset's** level. It is set on the NetBox device or VM (when its level is
  still empty), and it is what `--split` uses to separate a cell's controllers from its supervisory assets.

An asset without a level in the zone map takes the level NetBox already has for it, so a level you correct
by hand in NetBox counts on the next import.

```
network,zone,purdue_level,type
10.10.10.0/24,Cell A,1,ot
10.10.10.20,Cell A,2,
10.10.10.30,Cell A,2,
```

Here the PLCs and the HMI share zone *Cell A* (level 1); `--split "Cell A"` puts the HMI and the engineering
station at .30 in *Cell A (supervisory)*, so their reads and writes to the PLCs become flows.

## What is read

| Log | Protocol | Function from | Counted |
|---|---|---|---|
| `modbus` (Zeek) | Modbus TCP | `func` | every record |
| `modbus_detailed`, `modbus_read_write_multiple_registers`, `modbus_mask_write_register` (ICSNPP) | Modbus TCP | `func` | `request_response` = REQUEST |
| `s7comm` (ICSNPP) | S7comm | `function_name`, else `subfunction_name` | `is_orig` |
| `s7comm_plus` (ICSNPP) | S7comm-plus | `function_name`, else `opcode_name` | `is_orig` |
| `cip` (ICSNPP) | EtherNet/IP | `cip_service` | `direction` = request |
| `enip` (ICSNPP) | EtherNet/IP | `enip_command` | `is_orig` |
| `dnp3` (Zeek) | DNP3 | `fc_request` | every record |
| `dnp3_control` (ICSNPP) | DNP3 | `function_code` | `is_orig` |
| `bacnet`, `bacnet_property`, `bacnet_device_control` (ICSNPP) | BACnet/IP | `pdu_service` | `is_orig` |
| `opcua_binary` (ICSNPP) | OPC UA | `req_identifier_str`, else the message type | every record |
| `omron_fins_general` (ICSNPP) | Omron FINS | `command_code` | `icf_data_type` = Command |
| `hart_ip_general` (ICSNPP) | HART-IP | none | every record |
| `profinet_io_cm` (ICSNPP) | PROFINET (CM) | `operation_type` | every record |
| `mqtt_publish`, `mqtt_subscribe` (Zeek) | MQTT through a broker | `PUBLISH` and the topic | see below |
| `conn` | from Zeek's payload detection (`service`), else none | none | see below |

Every request runs from the connection's originator to its responder (`id.orig_h` -> `id.resp_h`, destination
port `id.resp_p`). Functions are classified as read, write, control or program by the table in
`netbox_ot/importers/functions.py`; the names above were checked against the ICSNPP parsers' own test
output.

**OPC UA Reverse Connect.** When the originator of an OPC UA connection sent a ReverseHello (`RHE`), the server
opened the connection and the client sends the requests over it. Those records then count the other way round:
from the responder (the client) to the originator (the server), with the client's listening port and connection
*reverse connect*. Without this the flow would point out of the PLC's zone and miss the access map.

**MQTT through a broker.** The responder of an MQTT connection is the broker. A topic a client published
(`mqtt_publish`, `from_client` T) that the broker delivered to another client (`from_client` F) or that another
client subscribed to (`mqtt_subscribe`, MQTT wildcards `+` and `#` honoured) becomes a request from the
publisher to the subscriber *through the broker*: connection *brokered*, the broker's address, its port and the
topic. Sparkplug B commands (`spBv1.0/<group>/NCMD|DCMD/...`) count as write; other topics are left
unclassified. The clients' own connections to the broker remain ordinary flows from `conn.log`. MQTT over TLS
(8883) shows only those connections: there is no topic to see.

From `conn.log`, a connection that no protocol log covers becomes a request with the protocol Zeek identified
from the payload (`rdp`, `ssh`, `ssl`, `modbus`, ...) or, when Zeek identified nothing, `tcp/<port>`: the
port is kept, no protocol is guessed from it. A TCP connection that was never answered (`S0`, `REJ`, ...) is
skipped; one-way UDP (syslog, SNMP traps) counts. The ports of answered TCP connections become the
responder's open ports. Multicast and broadcast destinations and IPv6 addresses are skipped.

A flow from an external zone is marked as remote access.

## Hosts NetBox does not know

Every import ends with the observed hosts that match no device or VM at the site and in the VRF, hosts inside
a zone first: these are the assets a passive capture found and nobody documented. `--unknown-report FILE.csv`
writes all of them with their zone, first/last seen, number of peers, what they answered (protocol and
port), what they used, and their open ports.

`--unknown-import DIR` writes those inside a zone of the plant as NetBox bulk-import files (devices,
interfaces, IP addresses); see the README. On a first visit, when NetBox is still empty, this is how the
capture becomes a device list: name what each host is, import the files, and run the import again.
