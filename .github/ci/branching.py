# ruff: noqa: E402, F821
# Appended to configuration.py by the CI job that runs the tests with netbox-branching installed. Its setup:
# a schema-aware DATABASES, its router, and netbox_branching as the last plugin.
from netbox_branching.utilities import DynamicSchemaDict

DATABASES = DynamicSchemaDict(DATABASES)
DATABASE_ROUTERS = ['netbox_branching.database.BranchAwareRouter']
PLUGINS = [*PLUGINS, 'netbox_branching']
