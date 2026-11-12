# Importing Zeek logs

`manage.py ot_import <dir> --site <slug>` reads a directory of Zeek logs directly, with or without the
[CISA ICSNPP](https://github.com/cisagov/ICSNPP) parsers, as Zeek or Malcolm write them. No converter needed.
The format is detected from the `conn` log; force it with `--format zeek`.

```bash
manage.py ot_import /captures/plant-a --site plant-a --dry-run
manage.py ot_import /captures/plant-a --site plant-a --zone-map zones.csv --unknown-report unknown.csv
```

Zeek TSV and JSON logs both work, plain or gzipped, rotated files included (`conn.00:00:00-01:00:00.log.gz`).

## Where addresses go: the zone map

Zeek knows addresses, not zones. The importer places each address in a zone from what NetBox already has
for the site, in the import's VRF (`--vrf`, default the global table):

1. the primary IPv4 address of a zone's member device or VM;
2. else the most specific prefix linked to a zone (a sub-zone wins over its parent).

Addresses in no zone go to the outside zone (`--outside-zone`, default `Outside`), which is created as an
external zone. For a first import, or for zones NetBox does not have yet (a supplier, an MSP), add a zone map:
a CSV file with `network or address, zone[, purdue_level][, type]` per line. Its lines win over NetBox.

```
network,zone,purdue_level,type
192.0.2.0/24,MSP,,external
10.10.30.0/24,Servers,3,
10.10.10.10,Cell A PLCs,1,
```

A zone named only in the zone map is created by the import, with the type given (`ot`, `safety`, `dmz`,
`enterprise`, `external`).

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
| `conn` | from Zeek's payload detection (`service`), else none | none | see below |

Every request runs from the connection's originator to its responder (`id.orig_h` -> `id.resp_h`, destination
port `id.resp_p`). Functions are classified as read, write, control or program by the table in
`netbox_ot/importers/functions.py`; the names above were checked against the ICSNPP parsers' own test
output.

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
