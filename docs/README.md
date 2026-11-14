# netbox-ot documentation

1. [Installation and configuration](installation.md): from source or netbox-docker, settings, permissions,
   upgrading, removing.
2. [Data model](data-model.md): zones, conduits, flows, risk assessments, Purdue levels and security levels,
   and why they are modelled this way. [Risk assessments](risk-assessments.md): the risk matrix and the steps
   of an assessment.
3. [Access map](access-map.md): who can reach the controllers, and whether that was decided.
4. [Consistency checks and the zone register](checks-and-register.md): what is missing before an audit, and the
   register you hand over.
5. [System requirements](requirements.md): IEC 62443-3-3 requirements and their status per zone or conduit,
   loaded from your own copy of the standard.
6. [Firewall rule export](firewall-rules.md): vendor-neutral rules from the allowed flows.
7. [Industrial systems and protocols](industrial.md): industrial services and fieldbuses.
8. [Importer](importer.md): Zeek logs ([zeek.md](zeek.md)) and observation files
   ([import-format.md](import-format.md)).
9. [REST API, GraphQL and management commands](api.md).
10. [OT overview](overview.md): where a site stands, as a radar chart of achieved against target security
    level, requirement statuses and risk.
11. [Companion plugins](companions.md): netbox-lifecycle and netbox-inventory, the tested bundle, end of support,
    firmware versions, a licence note.
12. [Working in a branch](branching.md): netbox-branching, `--branch` on the commands, a default branch for
    imports and a guard for main.
13. [Development](development.md): running the tests, CI, releasing, translations.

Release notes: [CHANGELOG.md](../CHANGELOG.md).
