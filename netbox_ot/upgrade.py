"""
After `migrate` took over a netbox-iec62443 installation (netbox_ot/adopt.py), the search index of the plugin's
models is rebuilt, so search results link to the new URLs.
"""
import logging

from . import adopt

APP_LABEL = 'netbox_ot'

logger = logging.getLogger('netbox.plugins.netbox_ot')


def reindex_search():
    """Rebuild the search cache of the plugin's models; returns the number of entries cached."""
    from netbox.registry import registry
    from netbox.search.backends import search_backend

    cached = 0
    for label, indexer in registry['search'].items():
        if label.startswith(f'{APP_LABEL}.'):
            cached += search_backend.cache(indexer.model.objects.iterator()) or 0
    return cached


def after_upgrade(sender=None, **kwargs):
    if not adopt.adopted:
        return
    adopt.adopted = False
    cached = reindex_search()
    logger.info('Rebuilt the search index of the plugin models (%s entries)', cached)
