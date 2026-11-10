# Changelog

## 0.1.0.dev0 (unreleased)

First development version, for NetBox 4.7.

- Zone and Conduit models with UI views, bulk import/edit/delete, filters, search, REST API and GraphQL.
- Purdue level custom field on devices and virtual machines, created after migrate.
- Access map per site (table and diagram), as a site tab and as a standalone page.
- IEC 62443 panel on device and VM pages.
- `iec62443_import` management command for observation files in a documented format
  (docs/import-format.md), with
  `--vrf`, `--outside-zone` and `--split`/`--split-all` (one zone per Purdue band). Devices, VMs and
  prefixes are matched only at the import's site and in its VRF; ambiguous matches are skipped and
  reported. The importer links existing prefixes and never creates them.
- OT requests are classified as read, write, control or program by an explicit table per protocol
  (Modbus, S7comm, S7comm-plus, EtherNet/IP, DNP3, IEC 104, IEC 61850 MMS, OPC UA, BACnet, Omron FINS),
  or by the flow's own `access` field. Remote access comes from the asset's `remote_access` field.
- An open port alone creates no industrial service; protocols come from decoded traffic or the asset's
  `services` field. Unexplained open OT ports are listed in the import output.
- Deleting a zone that still has conduits is refused, so verdicts and evidence are never lost.
- Industrial services (protocol, role, interface/ports or fieldbus/address) and fieldbuses (medium,
  protocol, zone, gateway), with UI, API, GraphQL and the device panel;
  the importer derives services from OT requests and open ports.
- REST endpoint `access-map/` (conduits + SVG per site) for reports and other tools.
- English only; all strings translatable, so the UI follows NetBox's language once translations exist.
