# netbox-ot documentation

1. [Installation and configuration](installation.md): from source or netbox-docker, settings, permissions,
   upgrading, removing.
2. [Data model](data-model.md): zones, conduits, flows, risk assessments, Purdue levels and security levels,
   and why they are modelled this way.
3. [Access map](access-map.md): who can reach the controllers, and whether that was decided.
4. [Consistency checks and the zone register](checks-and-register.md): what is missing before an audit, and the
   register you hand over.
5. [Firewall rule export](firewall-rules.md): vendor-neutral rules from the allowed flows.
6. [Industrial systems and protocols](industrial.md): industrial services and fieldbuses.
7. [Importer](importer.md): Zeek logs ([zeek.md](zeek.md)) and observation files
   ([import-format.md](import-format.md)).
8. [REST API, GraphQL and management commands](api.md).
9. [Development](development.md): running the tests, CI, releasing, translations.

Release notes: [CHANGELOG.md](../CHANGELOG.md).
