# Changelog

## 0.1.0.dev0 (unreleased)

First development version, for NetBox 4.7.

- Zone and Conduit models with UI views, bulk import/edit/delete, filters, search, REST API and GraphQL.
- Purdue level custom field on devices and virtual machines, created after migrate.
- Access map per site (table and diagram), as a site tab and as a standalone page.
- IEC 62443 panel on device and VM pages.
- `iec62443_import_vloerscan` management command for passive-capture analysis output, with
  `--rename`, `--outside-zone` and `--split`/`--split-all` (one zone per Purdue band).
- Industrial services (protocol, role, interface/ports or fieldbus/address) and fieldbuses (medium,
  protocol, baud rate, frame format, zone, gateway), with UI, API, GraphQL and the device panel;
  the importer derives services from OT requests and open ports.
- REST endpoint `access-map/` (conduits + SVG per site) for report builders.
- English only; all strings translatable, so the UI follows NetBox's language once translations exist.
