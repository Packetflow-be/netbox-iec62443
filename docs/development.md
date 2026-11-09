# Development with netbox-docker

The plugin source is mounted read-only into the NetBox container and put on `PYTHONPATH`.

`docker-compose.override.yml`:

```yaml
services:
  netbox:
    ports:
      - "8080:8080"
    volumes:
      - /path/to/netbox-iec62443:/opt/netbox-plugins/netbox-iec62443:ro
    environment:
      PYTHONPATH: /opt/netbox-plugins/netbox-iec62443
```

`configuration/plugins.py`:

```python
PLUGINS = ["netbox_iec62443"]
PLUGINS_CONFIG = {"netbox_iec62443": {}}
```

Then `docker compose up -d netbox`; the entrypoint applies the migrations. After code changes,
`docker restart <netbox container>`. If you also run `netbox-worker`, give it the same volume and
environment.

Run the tests in a throwaway container (uses a separate `test_netbox` database):

```
docker compose run --rm --no-deps -T netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_iec62443 --keepdb --noinput
```

New migrations need developer mode and a writable checkout:

```
docker compose run --rm --no-deps -T -e DEVELOPER=True netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_iec62443 --dry-run -v 3
```

(`--dry-run -v 3` prints the migration file, which also works with the read-only mount.)

Importer against a running instance:

```
docker cp observations/ <netbox container>:/tmp/observations
docker exec <netbox container> /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py \
  iec62443_import /tmp/observations --site <site-slug> [--split "<zone>"] --dry-run
```
