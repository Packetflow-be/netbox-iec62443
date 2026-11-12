# Firewall rule export

The flows a person allowed become vendor-neutral firewall rules: source and destination zone with their
networks (the zone's prefixes, else its members' addresses), transport, ports, the protocol, what the requests
do, and the devices that enforce the conduit. One rule per flow and transport.

A rule follows the connection the firewall sees, not the direction of the flow
([connection models](data-model.md#connection-models)): a reverse-connect flow is opened by its destination
zone, and a flow through a broker gives one rule from each end's zone to the broker zone. The column
`connection` says which.

- Flows without a verdict are not exported; not-allowed and expired flows become deny rules on request.
- Ports the capture did not show are filled in from the protocol's defaults and flagged.
- A layer-2 protocol (GOOSE, EtherCAT) is flagged as not enforceable by a routed firewall.
- The plugin writes no vendor syntax and reads no vendor configuration: the export is the input for your own
  conversion or review.

Where to get it:

- *Firewall rules (CSV)* on a site's *Zone register* tab.
- `GET /api/plugins/ot/firewall-rules/?site_id=<id>[&device_id=<id>][&include_denied=true]`.
- `manage.py ot_rules [--site <slug>] [--device <firewall>] [--include-denied] [--format csv|json]
  [--output FILE]`.

`device_id` / `--device` limits the export to the conduits one firewall enforces.
