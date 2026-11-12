# System requirements (IEC 62443-3-3)

An auditor asks, per zone, which system requirements apply at its SL-T and how each is met. The plugin records
that per zone and per conduit (a conduit has an SL-T of its own): *OT > Requirement statuses*, a table on every
zone and conduit page, a *System requirements* table and CSV in the [zone register](checks-and-register.md), and
two checks.

A status is one of *met*, *met by a compensating countermeasure* (the countermeasure is then required), *not
met* or *not applicable*, with the evidence, the risk assessment behind it (of the same zone or conduit), who
assessed it and when. There is one status per zone or conduit and requirement.

## Loading the requirements

The requirement texts and the table of which requirement (or requirement enhancement) applies from which
security level are copyrighted parts of the standard. The plugin ships **identifiers and foundational
requirements only** (`netbox_ot/data/iec62443-3-3-2013.csv`: SR 1.1 to SR 7.8). Load them, and then whatever you
take from your own licensed copy:

```bash
manage.py ot_requirements                    # the 51 identifiers, once
manage.py ot_requirements --csv my-copy.csv  # enhancements, levels and wording from your copy
```

`my-copy.csv` has a header row and the columns `identifier` (`SR 1.1`, `SR 1.1 RE 1`), and optionally
`security_level` (the lowest SL, 1 to 4, at which the requirement applies), `wording` and
`foundational_requirement` (it follows from the identifier; a contradicting value is refused). An empty cell
leaves what is stored; an enhancement gets its requirement as parent. `--dry-run` shows what would change;
`--branch` works as for the other commands ([Working in a branch](branching.md)). Keep that file and your
database to yourself: the wording stays in your installation.

## Checks

With the levels loaded, the checks find, per zone and conduit:

- `requirements-without-status` (warning): requirements that apply at its SL-T and have no status yet;
- `requirement-not-met-for-sl-a` (error): a requirement marked *not met* that applies at the SL-A the zone or
  conduit claims.

Without levels loaded the plugin cannot tell what applies, so these checks stay silent; statuses can still be
recorded. Requirement identifiers are per edition (3-3:2013 today), so a later edition can be loaded next to it
rather than migrated.

## API

REST `/api/plugins/ot/system-requirements/` and `/api/plugins/ot/requirement-statuses/`; GraphQL
`ot_system_requirement_list` and `ot_requirement_status_list`.
