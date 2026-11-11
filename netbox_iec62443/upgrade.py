"""
What the upgrade from a 0.1.0.dev0 development build cannot do inside its migrations, done right after `migrate`.

Migration 0006 creates conduits with the model of that moment, which NetBox cannot index for search, and the
conduit and flow hop object types exist only once the migrations are through. So when 0006 was part of this
`migrate` run:

- the search index of the plugin's models is rebuilt;
- every permission on flows (the old conduits, renamed in place) also covers the new conduit and flow hop
  models, with the same actions. A permission with constraints is left alone and reported: its constraints
  were written for the old model.

On a new installation 0006 runs too, on empty tables: nothing to index and no permission on flows yet.
"""
import logging

APP_LABEL = 'netbox_iec62443'
DATA_MIGRATION = '0006_'

logger = logging.getLogger('netbox.plugins.netbox_iec62443')


def data_migration_ran(plan):
    return any(
        migration.app_label == APP_LABEL and migration.name.startswith(DATA_MIGRATION) and not backwards
        for migration, backwards in plan or ()
    )


def reindex_search():
    """Rebuild the search cache of the plugin's models; returns the number of entries cached."""
    from netbox.registry import registry
    from netbox.search.backends import search_backend

    cached = 0
    for label, indexer in registry['search'].items():
        if label.startswith(f'{APP_LABEL}.'):
            cached += search_backend.cache(indexer.model.objects.iterator()) or 0
    return cached


def extend_flow_permissions():
    """Permissions on flows also get conduits and flow hops; returns the permissions that were extended."""
    from core.models import ObjectType
    from users.models import ObjectPermission

    from .models import Conduit, Flow, FlowHop

    flow = ObjectType.objects.get_for_model(Flow)
    conduit = ObjectType.objects.get_for_model(Conduit)
    flow_hop = ObjectType.objects.get_for_model(FlowHop)
    extended = []
    for permission in ObjectPermission.objects.filter(object_types=flow).exclude(object_types=conduit):
        if permission.constraints:
            logger.warning(
                'Permission "%s" has constraints and was not extended to conduits and flow hops', permission.name
            )
            continue
        permission.object_types.add(conduit, flow_hop)
        extended.append(permission)
    return extended


def after_upgrade(sender=None, plan=None, **kwargs):
    if not data_migration_ran(plan):
        return
    cached = reindex_search()
    if cached:
        logger.info('Rebuilt the search index of the IEC 62443 models (%s entries)', cached)
    for permission in extend_flow_permissions():
        logger.info('Permission "%s" now also covers conduits and flow hops', permission.name)
