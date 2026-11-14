# Working in a branch

> **Not recommended alongside netbox-ot.** It works, but every netbox-ot release that brings a database
> migration leaves each existing branch with *pending migrations*. Migrating a branch can take long and hold
> up NetBox while it runs, so in practice you delete your branches and rebuild them after every upgrade.
> To try an import before it lands, use `ot_import --dry-run` (it shows every change and saves nothing), a
> separate site, or a test NetBox instead. If you use branches anyway, keep them short-lived: merge or delete
> them before you upgrade netbox-ot.

With the [netbox-branching](https://github.com/netboxlabs/netbox-branching) plugin installed, a branch is the
place to try an import: load a capture, look at the zones, the flows and the access map, then merge the branch
or throw it away. The plugin's models are change-logged, so they are branched like NetBox's own.

netbox-branching is a separately licensed optional plugin (NetBox Limited Use License 1.0: internal use only).
netbox-ot does not depend on it, installs it nowhere and imports it only when it is in `PLUGINS`; keep it out of
any image or requirements file you hand to others. See also [Companion plugins](companions.md).

## Pages and the REST API

- **Pages** follow the branch picked in NetBox's menu: zones, flows, the access map, the register and the checks
  all show that branch.
- **REST API**: send the header `X-NetBox-Branch: <schema id>` (the branch's schema ID, shown on the branch);
  without it a request reads and writes main.

## Commands

A `manage.py` command runs outside a web request, so it works on main unless told otherwise. `--branch NAME` on
`ot_import`, `ot_demo`, `ot_check` and `ot_rules` runs the whole command in that branch; the branch must exist
and be ready. The command says on stderr where it worked.

```bash
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py ot_import ./observations --site plant-a --branch trial
```

## Settings

*OT > Settings* is shown only with netbox-branching installed and needs the `netbox_ot.change_pluginsettings`
permission (superusers have it).

- *Use a branch for imports* with a *default branch*: `ot_import` and `ot_demo` without `--branch` then run in
  that branch, and say so. `--main` forces main.
- *Refuse imports into main*: those two commands will not write to main at all, `--main` included, so test data
  cannot land in the real inventory by accident. A `--dry-run` import still runs.

`ot_check` and `ot_rules` only read; they ignore the default branch, so a nightly check keeps watching main. The
settings themselves are not branched: they are the same whichever branch is active.

## Things to know

- NetBox's `CUSTOM_VALIDATORS` (naming rules, for example) apply inside a branch as they do in main, so an import
  that would be refused in main is refused in the branch too.
- A merge replays the branch's change log. Changes are only visible in a branch's *Diff* and *Changes ahead*
  tabs, and only carried to main by a merge, when they were change-logged; the importer and the demo do that
  (under `--user`, default the first superuser).
- After a NetBox upgrade, branches need migrating before commands can use them (they are not *ready* until then).
