# Security policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue or discussion: use
[Report a vulnerability](https://github.com/Packetflow-be/netbox-ot/security/advisories/new) on the
repository's *Security* tab (GitHub private vulnerability reporting).

Include the plugin and NetBox versions, what an attacker can do, and the steps to reproduce. We aim to answer
within a week. Fixes are released as a patch version and announced in a GitHub security advisory.

## Supported versions

Only the newest release gets security fixes while the plugin is in alpha (0.x).

## Scope

The plugin runs inside NetBox with NetBox's privileges. Issues in NetBox itself belong to the
[NetBox project](https://github.com/netbox-community/netbox/security/policy). The plugin stores a model of an
OT network (zones, flows, remote-access paths); treat a NetBox with this data as sensitive and give its users
only the permissions they need.
