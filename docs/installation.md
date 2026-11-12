# Installation and configuration

The plugin needs NetBox 4.7 (4.8 is allowed; see [Compatibility](../README.md#compatibility)) and nothing else:
no other plugins, Python packages or external services. It has no static files of its own.

## NetBox installed from source

These steps assume the standard install in `/opt/netbox`.

1. Install the package into NetBox's virtual environment, and add it to `local_requirements.txt` so NetBox's
   `upgrade.sh` installs it again after a NetBox upgrade:

   ```bash
   cd /opt/netbox
   echo "netbox-iec62443" | sudo tee -a local_requirements.txt
   sudo venv/bin/pip install netbox-iec62443
   ```

   For a build that is not released yet, install from GitHub instead:
   `pip install "netbox-iec62443 @ git+https://github.com/Packetflow-be/netbox-iec62443.git"`.

2. Enable it in `/opt/netbox/netbox/netbox/configuration.py`. If `PLUGINS` already lists other plugins, add
   `"netbox_iec62443"` to that list instead of replacing it:

   ```python
   PLUGINS = ["netbox_iec62443"]
   PLUGINS_CONFIG = {
       "netbox_iec62443": {},   # defaults; see Configuration below
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
   netbox-iec62443
   ```

2. `Dockerfile-Plugins` (use the same NetBox image tag as in your `docker-compose.yml`):

   ```dockerfile
   FROM netboxcommunity/netbox:v4.7
   COPY ./plugin_requirements.txt /opt/netbox/
   RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt
   ```

3. `configuration/plugins.py`:

   ```python
   PLUGINS = ["netbox_iec62443"]
   PLUGINS_CONFIG = {"netbox_iec62443": {}}
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

The plugin shows up under *Admin > System > Plugins*, as an *IEC 62443* menu, and in the API status:

```bash
curl -s -H "Authorization: Token $TOKEN" https://netbox.example.com/api/status/ | grep netbox_iec62443
```

## Try it with the demo plant

`iec62443_demo` creates a fictional plant: zones, conduits, flows, an MSP remote-access path, industrial
services, risk assessments and a few things the checks will flag. Open the site *IEC 62443 demo plant* and its
*Access map* and *Zone register* tabs. `--delete` removes exactly what the command created.

```bash
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py iec62443_demo
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py iec62443_demo --delete
```

With netbox-docker: `docker compose exec netbox /opt/netbox/netbox/manage.py iec62443_demo`.

## Configuration

All settings are optional; these are the defaults.

```python
PLUGINS_CONFIG = {
    "netbox_iec62443": {
        "create_custom_fields": True,     # create the Purdue level and SL-C custom fields after migrate
        "access_map_max_level": "2",      # default level filter of the access map
        "stale_after_days": 90,           # a flow not seen for this long needs attention
    },
}
```

| Setting | Default | What it does |
|---|---|---|
| `create_custom_fields` | `True` | After `migrate`, create the custom fields `iec62443_purdue_level` (devices, VMs) and `iec62443_sl_capability` (devices, device types) if they don't exist. Existing fields are never changed, so you may relabel them. Set `False` to manage them yourself. |
| `access_map_max_level` | `"2"` | The access map shows flows into zones at this Purdue level or below unless the user picks another level. One of `"0"`, `"1"`, `"2"`, `"3"`, `"3.5"`, `"4"`, `"5"`. |
| `stale_after_days` | `90` | A flow whose *last seen* is older than this is listed under *Needs attention* and by the checks. |

## Permissions

The plugin uses NetBox's object permissions for its models (zone, conduit, flow, flow hop, risk assessment,
industrial service, fieldbus). Users who view flows also need view permission on zones (a flow shows its
zones). The access map needs `view_flow`; the checks and the zone register need `view_zone`.

## Language

The plugin is written in English and every user-facing string goes through Django's translation functions,
so it follows the language of the NetBox install (`LANGUAGE_CODE`, or each user's language preference) as
soon as a translation exists. No translations ship yet; see [development.md](development.md#translations).

## Upgrading

Upgrade the package and run the migrations again:

```bash
sudo /opt/netbox/venv/bin/pip install --upgrade netbox-iec62443
sudo /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
sudo systemctl restart netbox netbox-rq
```

With netbox-docker, rebuild the image (`docker compose build --no-cache`) and `docker compose up -d`. Read the
[changelog](../CHANGELOG.md) first: breaking changes are listed under a **Breaking Changes** header.

### From a 0.1.0.dev0 development build

Earlier builds had a single "conduit" model that was really a directed zone pair with a verdict. The
migrations turn it into the current model; nothing is deleted:

- Every old conduit becomes a **flow** with the same id, verdict, evidence, tags, journal and change
  history. Its free-text "protocols" and "via" cannot become structured ports or hops, so they are kept in
  the flow's comments. A two-way conduit becomes two flows. A yes/no verdict is dated with its last change.
- For every pair of zones that had flows, one **conduit** is created joining both zones, and the flows are
  put in it. Rename or merge them to match your 62443-3-2 design.
- Zones get a **type** from their Purdue level (3.5: DMZ, 4-5: enterprise, the rest: OT). Set supplier and
  safety zones by hand.
- A single **SL-T** number on a zone or conduit becomes the vector with that level for every FR.
- **Industrial services** that listen get a NetBox application service with their ports (bound to the IP
  addresses of their interface) and are linked to it. Ports on clients are dropped (noted in comments when
  they were not the protocol's defaults).

Permissions, saved filters, export templates and event rules that pointed at the old conduit now point at
flows. Right after `migrate`, the plugin gives every permission on flows the new *conduit* and *flow hop*
models too (a permission with constraints is left alone and logged: extend it by hand) and rebuilds the
search index of its models. Risk assessments are new: grant permissions on them yourself.

The REST endpoint `access-map/` now returns `flows` (structured protocol, ports, access and hops) where it
returned `conduits` with free text, and no longer carries the SVG diagram; the diagram is on the access map
page.

## Removing

Take `netbox_iec62443` out of `PLUGINS`, restart NetBox, then `pip uninstall netbox-iec62443` (and remove it
from `local_requirements.txt` or `plugin_requirements.txt`). The plugin's tables and custom fields stay until
you drop them.
