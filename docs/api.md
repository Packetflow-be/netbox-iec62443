# REST API and GraphQL

All endpoints live under `/api/plugins/iec62443/` and use NetBox's own authentication, permissions, filtering,
pagination and `brief` mode. The browsable API and NetBox's OpenAPI schema (`/api/schema/`) describe every
field.

## Objects

| Endpoint | Object |
|---|---|
| `zones/` | Zones |
| `conduits/` | Conduits |
| `flows/` | Flows |
| `flow-hops/` | Ordered hops of a flow (device, VM or VPN tunnel) |
| `risk-assessments/` | Risk assessments of zones and conduits |
| `industrial-services/` | Industrial services on devices and VMs |
| `fieldbuses/` | Fieldbuses |

Security level vectors (SL-T, SL-A) are lists of seven levels in FR order IAC, UC, SI, DC, RDF, TRE, RA. A
flow's ports are in `port_mappings`, in NetBox's `protocol/port` format (`tcp/502`).

Useful flow filters: `site_id`, `source_zone_id`, `destination_zone_id`, `conduit_id`, `protocol`, `allowed`,
`remote_access`, `modifying` (write, control or program access), `hop_device_id`.

## Views

| Endpoint | Returns | Needs |
|---|---|---|
| `GET access-map/?site_id=<id>[&max_level=<level>]` | The flows into zones at that Purdue level or below, in access-map order, with their hops ([Access map](access-map.md)) | `view_flow` |
| `GET checks/?site_id=<id>[&severity=...][&check=...]` | Consistency check findings ([Checks](checks-and-register.md)) | `view_zone` |
| `GET register/?site_id=<id>` | The site's zone and conduit register as JSON ([Register](checks-and-register.md#zone-register)) | `view_zone` |
| `GET firewall-rules/?site_id=<id>[&device_id=<id>][&include_denied=true]` | Vendor-neutral firewall rules ([Firewall rules](firewall-rules.md)) | `view_flow` |

## GraphQL

Each object has a single and a list query: `iec62443_zone` / `iec62443_zone_list`, `iec62443_conduit(_list)`,
`iec62443_flow(_list)`, `iec62443_flow_hop(_list)`, `iec62443_risk_assessment(_list)`,
`iec62443_fieldbus(_list)` and `iec62443_industrial_service(_list)`.

```graphql
{
  iec62443_flow_list(filters: {remote_access: {exact: true}}) {
    source_zone { name }
    destination_zone { name }
    protocol
    port_mappings
    allowed
  }
}
```

## Management commands

| Command | Does |
|---|---|
| `iec62443_demo [--delete]` | Creates (or removes) the fictional demo plant |
| `iec62443_import <dir> --site <slug> ...` | Imports Zeek logs or observation files ([Importer](importer.md)) |
| `iec62443_check [--site <slug>] [--fail-on ...] [--json]` | Runs the consistency checks; exit status 1 on findings |
| `iec62443_rules [--site <slug>] [--device <firewall>] [--format csv\|json]` | Exports firewall rules |
