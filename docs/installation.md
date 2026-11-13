# Installation and configuration

The plugin needs NetBox 4.7 (4.8 is allowed; see [Compatibility](../README.md#compatibility)) and nothing else:
no other plugins, Python packages or external services. It has no static files of its own.

## NetBox installed from source

These steps assume the standard install in `/opt/netbox`.

1. Install the package into NetBox's virtual environment, and add it to `local_requirements.txt` so NetBox's
   `upgrade.sh` installs it again after a NetBox upgrade:

   ```bash
   cd /opt/netbox
   echo "netbox-ot" | sudo tee -a local_requirements.txt
   sudo venv/bin/pip install netbox-ot
   ```

   For a build that is not released yet, install from GitHub instead:
   `pip install "netbox-ot @ git+https://github.com/Packetflow-be/netbox-ot.git"`.

2. Enable it in `/opt/netbox/netbox/netbox/configuration.py`. If `PLUGINS` already lists other plugins, add
   `"netbox_ot"` to that list instead of replacing it:

   ```python
   PLUGINS = ["netbox_ot"]
   PLUGINS_CONFIG = {
       "netbox_ot": {},   # defaults; see Configuration below
   }
   ```

3. Create the plugin's tables and restart NetBox:

   ```bash
   sudo venv/bin/python netbox/manage.py migrate
   sudo venv/bin/python netbox/manage.py collectstatic --no-input
   sudo systemctl restart netbox netbox-rq
   ```

## netbox-docker

[netbox-docker](https://github.com/netbox-community/netbox-docker) needs a custom image with the plugin in it.
In your netbox-docker checkout:

1. `plugin_requirements.txt`:

   ```
   netbox-ot
   ```

2. `Dockerfile-Plugins` (use the same NetBox image tag as in your `docker-compose.yml`):

   ```dockerfile
   FROM netboxcommunity/netbox:v4.7
   COPY ./plugin_requirements.txt /opt/netbox/
   RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt
   ```

3. `configuration/plugins.py`:

   ```python
   PLUGINS = ["netbox_ot"]
   PLUGINS_CONFIG = {"netbox_ot": {}}
   ```

4. `docker-compose.override.yml`: build that image and use it for every NetBox container:

   ```yaml
   services:
     netbox:
       image: netbox:latest-plugins
       pull_policy: never
       ports:
         - "8000:8080"
       build:
         context: .
         dockerfile: Dockerfile-Plugins
     netbox-worker:
       image: netbox:latest-plugins
       pull_policy: never
   ```

5. Build and start; the container runs the migrations when it starts:

   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```

The [netbox-docker wiki page on plugins](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins)
has the background and variants of these steps.

## Check that it works

The plugin shows up under *Admin > System > Plugins*, as an *OT* menu, and in the API status:

```bash
curl -s -H "Authorization: Token $TOKEN" https://netbox.example.com/api/status/ | grep netbox_ot
```

## Try it with the demo plant

`ot_demo` creates a fictional plant: zones, conduits, flows, an MSP remote-access path, industrial
services, risk assessments and a few things the checks will flag. Open the site *IEC 62443 demo plant* and its
*Access map* and *Zone register* tabs. `--delete` removes exactly what the command created.

```bash
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py ot_demo
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py ot_demo --delete
```

With netbox-docker: `docker compose exec netbox /opt/netbox/netbox/manage.py ot_demo`.

## Configuration

All settings are optional; these are the defaults.

```python
PLUGINS_CONFIG = {
    "netbox_ot": {
        "create_custom_fields": True,     # create the Purdue level, SL-C and firmware version custom fields after migrate
        "access_map_max_level": "2",      # default level filter of the access map
        "stale_after_days": 90,           # a flow not seen for this long needs attention
        "risk_matrix": None,              # your own risk matrix; None is the default 5 x 5
    },
}
```

| Setting | Default | What it does |
|---|---|---|
| `create_custom_fields` | `True` | After `migrate`, create the custom fields `ot_purdue_level` (devices, VMs), `ot_sl_capability` (devices, device types) and `ot_firmware_version` (devices, modules) if they don't exist. Existing fields are never changed, so you may relabel them. Set `False` to manage them yourself. |
| `access_map_max_level` | `"2"` | The access map shows flows into zones at this Purdue level or below unless the user picks another level. One of `"0"`, `"1"`, `"2"`, `"3"`, `"3.5"`, `"4"`, `"5"`. |
| `stale_after_days` | `90` | A flow whose *last seen* is older than this is listed under *Needs attention* and by the checks. |
| `risk_matrix` | `None` | The organisation's risk matrix (likelihood by impact) for risk assessments; see [Risk assessments](risk-assessments.md#your-own-matrix). `None` is a common 5 x 5. |

## Permissions

The plugin uses NetBox's object permissions for its models (zone, conduit, flow, flow hop, risk assessment,
system requirement, requirement status, industrial service, fieldbus). Users who view flows also need view
permission on zones (a flow shows its zones). The access map needs `view_flow`; the checks and the zone register need `view_zone`.

## Language

The plugin is written in English and every user-facing string goes through Django's translation functions,
so it follows the language of the NetBox install (`LANGUAGE_CODE`, or each user's language preference) as
soon as a translation exists. No translations ship yet; see [development.md](development.md#translations).

## Upgrading

Upgrade the package and run the migrations again:

```bash
sudo /opt/netbox/venv/bin/pip install --upgrade netbox-ot
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
sudo systemctl restart netbox netbox-rq
```

With netbox-docker, rebuild the image (`docker compose build --no-cache`) and `docker compose up -d`. Read the
[changelog](../CHANGELOG.md) first: breaking changes are listed under a **Breaking Changes** header.

### From netbox-iec62443

Up to 0.2.0 this plugin was called **netbox-iec62443** (Django app `netbox_iec62443`). netbox-ot 0.3.0 takes
an installation of the old name over in place: its first migration renames the old tables instead of creating
new ones, so nothing is exported or re-imported. The old installation must be at netbox-iec62443 **0.2.0**;
upgrade that first if it is older (the migration stops with a message, before it changes anything, when it
is not).

1. Back up the database (`pg_dump netbox`).
2. Install netbox-ot and swap the plugin name. In `local_requirements.txt` (or netbox-docker's
   `plugin_requirements.txt`) replace `netbox-iec62443` with `netbox-ot`; in `configuration.py`:

   ```python
   PLUGINS = ["netbox_ot"]                     # was "netbox_iec62443"; never both (NetBox refuses to start)
   PLUGINS_CONFIG = {"netbox_ot": {...}}       # the same settings as before, under the new name
   ```

3. Migrate and restart, as for any upgrade:

   ```bash
   sudo /opt/netbox/venv/bin/pip install netbox-ot
   sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
   sudo systemctl restart netbox netbox-rq
   sudo /opt/netbox/venv/bin/pip uninstall -y netbox-iec62443
   ```

What the first migration does on the old installation:

- every table, sequence, index and constraint called `netbox_iec62443_*` becomes `netbox_ot_*`;
- the content types move to the app label `netbox_ot` and keep their IDs, so permissions, tags, journal
  entries, the change log, custom fields on the plugin's models, saved filters, export templates, event rules
  and bookmarks keep working;
- the custom fields `iec62443_purdue_level` and `iec62443_sl_capability` are renamed `ot_purdue_level` and
  `ot_sl_capability`, values included; dashboard widgets that named an old model are rewritten;
- the search index of the plugin's models is rebuilt.

What changes for you:

| Before | Now |
|---|---|
| `pip install netbox-iec62443` | `pip install netbox-ot` |
| `PLUGINS = ["netbox_iec62443"]` | `PLUGINS = ["netbox_ot"]` |
| `/plugins/iec62443/...`, `/api/plugins/iec62443/...` | `/plugins/ot/...`, `/api/plugins/ot/...` |
| `manage.py iec62443_import`, `_demo`, `_check`, `_rules` | `manage.py ot_import`, `ot_demo`, `ot_check`, `ot_rules` |
| custom fields `iec62443_purdue_level`, `iec62443_sl_capability` (filters `cf_iec62443_...`) | `ot_purdue_level`, `ot_sl_capability` (`cf_ot_...`) |
| site tab URL `.../iec62443-register/` | `.../ot-register/` |
| menu *IEC 62443* | menu *OT* |
| permission names `netbox_iec62443.view_zone` | `netbox_ot.view_zone` (the same permission objects) |
| GraphQL, related names `iec62443_zones` on devices, sites, ... | `ot_zones`, ... |

Scripts and saved filters that name the old URLs, command names, custom fields or a permission constraint over
`iec62443_*` related names need the new names by hand. With
[netbox-branching](https://github.com/netboxlabs/netbox-branching), each branch shows *pending migrations*
after the upgrade; migrating the branch takes over its copy of the tables the same way.

## Removing

Take `netbox_ot` out of `PLUGINS`, restart NetBox, then `pip uninstall netbox-ot` (and remove it
from `local_requirements.txt` or `plugin_requirements.txt`). The plugin's tables and custom fields stay until
you drop them.
