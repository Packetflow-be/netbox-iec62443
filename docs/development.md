# Development

## With netbox-docker

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

## Without Docker

Any NetBox source checkout works, with PostgreSQL and Redis running locally:

```bash
git clone --depth 1 --branch v4.7.4 https://github.com/netbox-community/netbox.git
python3.12 -m venv venv && venv/bin/pip install -r netbox/requirements.txt
venv/bin/pip install -e /path/to/netbox-iec62443
# netbox/netbox/netbox/configuration.py: DATABASES, REDIS, SECRET_KEY, API_TOKEN_PEPPERS and
#   PLUGINS = ["netbox_iec62443"]   (.github/ci/configuration.py is a complete example)
cd netbox/netbox
../../venv/bin/python manage.py migrate
../../venv/bin/python manage.py test netbox_iec62443 --keepdb --parallel 4
../../venv/bin/python manage.py iec62443_demo     # a populated plant to look at
```

With `--parallel`, Django reuses cloned test databases (`test_netbox_1`, ...) when `--keepdb` is given. After
a new migration, drop the clones (`dropdb test_netbox_1` ...) or they stay at the old schema and the run fails
with "cannot pickle 'traceback' object" (a failure in a worker that cannot be reported).

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and push, and weekly:

- `ruff check .`;
- the test suite and a migration check (`makemigrations --check`) on NetBox 4.7.0, the newest 4.7 release and
  NetBox's `feature` branch. The `feature` run may fail without failing the workflow: it is the early warning
  for the next NetBox release. Query counts are asserted only on the newest 4.7 release; the other versions
  record them;
- a package build with `twine check` and a check that the wheel holds the templates and migrations.

## Releasing

1. Set `__version__` in `netbox_iec62443/__init__.py` and move the changelog entries under the new version.
   Each release in `CHANGELOG.md` opens with one sentence saying whether it is a major, minor or patch release
   and whether it holds bug fixes, new features, enhancements or all of these; lists breaking changes under a
   bold **Breaking Changes** header with links to their issues or pull requests; and links every entry to its
   issue or pull request. Add a row to the compatibility table in `README.md` when the supported NetBox range
   changes.
2. Merge to `main`, then tag: `git tag v0.1.0 && git push origin v0.1.0`.
3. The `publish` job builds the package and uploads it to PyPI once lint, tests and build pass, and only if the
   tag matches `__version__`.

Publishing uses PyPI trusted publishing, so no token is stored in GitHub. Once, before the first release:
on PyPI, add a trusted publisher for the project `netbox-iec62443` (owner `Packetflow-be`, repository
`netbox-iec62443`, workflow `ci.yml`, environment `pypi`), and in the GitHub repository create the environment
`pypi` (Settings > Environments), optionally with required reviewers.

## Query-count baselines

The view and API tests assert how many queries a list page takes. The baselines live in
`netbox_iec62443/tests/query_counts.json`, recorded on the newest 4.7 release; re-record them with
`UPDATE_QUERY_COUNTS=1` (from a writable checkout, without `--parallel`).

## Translations

Every user-facing string goes through Django's translation functions. A translation goes in
`netbox_iec62443/locale/<lang>/LC_MESSAGES/django.po`: run `manage.py makemessages -l <lang>` in the plugin
directory, translate, then `manage.py compilemessages`. Pull requests with a translation are welcome.
