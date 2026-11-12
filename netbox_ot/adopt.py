"""
netbox-ot was called netbox-iec62443 up to 0.2.0 (Django app `netbox_iec62443`). Its first migration takes over
an installation of the old name in place instead of creating empty tables, so nothing has to be exported or
re-imported:

- every table, sequence, index and constraint named `netbox_iec62443_*` in the current schema is renamed to
  `netbox_ot_*`;
- the content types move to the app label `netbox_ot`, so object IDs, permissions, tags, journal entries, change
  log, custom fields on the plugin's models, saved filters and bookmarks keep pointing at the same objects;
- the custom fields `iec62443_purdue_level` and `iec62443_sl_capability` become `ot_purdue_level` and
  `ot_sl_capability`, values included;
- dashboard widgets and other user preferences that name a `netbox_iec62443.*` model are rewritten;
- the old app's rows in `django_migrations` are removed.

The old installation must be at the last migration netbox-iec62443 released (0.2.0); anything else stops the
migration before it changes a thing. Without a netbox-iec62443 installation the tables are created as usual.

It works on the current schema, so a netbox-branching branch is taken over when the branch is migrated.
"""
import logging

from django.db.migrations.operations.base import Operation

OLD_APP = 'netbox_iec62443'
NEW_APP = 'netbox_ot'
OLD_LAST_MIGRATION = '0010_drop_single_security_level'
OLD_PREFIX = f'{OLD_APP}_'
NEW_PREFIX = f'{NEW_APP}_'
CUSTOM_FIELD_RENAMES = {
    'iec62443_purdue_level': 'ot_purdue_level',
    'iec62443_sl_capability': 'ot_sl_capability',
}

logger = logging.getLogger('netbox.plugins.netbox_ot')

# Set when this process took over an old installation; post_migrate then rebuilds the search index.
adopted = False


class AdoptionError(RuntimeError):
    pass


def old_installation(cursor):
    """True when the current schema holds a netbox-iec62443 installation at its last released migration."""
    cursor.execute('SELECT name FROM django_migrations WHERE app = %s', [OLD_APP])
    applied = {row[0] for row in cursor.fetchall()}
    if not applied:
        return False
    if OLD_LAST_MIGRATION not in applied:
        raise AdoptionError(
            f'netbox-iec62443 is installed but not at its last release (migration {OLD_LAST_MIGRATION}). Upgrade '
            'it to netbox-iec62443 0.2.0 and run migrate first, then install netbox-ot.'
        )
    unknown = sorted(name for name in applied if name > OLD_LAST_MIGRATION)
    if unknown:
        raise AdoptionError(
            f'netbox-iec62443 has migrations applied that no release contains ({", ".join(unknown)}): a development '
            f'build. Migrate it back first: manage.py migrate {OLD_APP} {OLD_LAST_MIGRATION}'
        )
    cursor.execute('SELECT to_regclass(%s)', [f'{OLD_PREFIX}zone'])
    if cursor.fetchone()[0] is None:
        raise AdoptionError(f'django_migrations lists {OLD_APP} but its tables are missing from the current schema.')
    return True


def rename_database_objects(cursor, quote, old_prefix=OLD_PREFIX, new_prefix=NEW_PREFIX):
    """Rename the tables, sequences, indexes and constraints in the current schema named old_prefix*."""
    def new_name(name):
        return new_prefix + name[len(old_prefix):]

    like = old_prefix.replace('_', r'\_') + '%'
    # Constraints without an index of their own (foreign keys, checks, not-null); index-backed ones (primary key,
    # unique, exclusion) are renamed with their index below.
    cursor.execute(
        """
        SELECT t.relname, c.conname FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = current_schema() AND t.relname LIKE %s AND c.conname LIKE %s
          AND c.contype NOT IN ('p', 'u', 'x')
        """,
        [like, like],
    )
    for table, constraint in cursor.fetchall():
        cursor.execute(
            f'ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(constraint)} TO {quote(new_name(constraint))}'
        )
    counts = {}
    for relkind, statement in (('i', 'ALTER INDEX'), ('S', 'ALTER SEQUENCE'), ('r', 'ALTER TABLE')):
        cursor.execute(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relkind = %s AND c.relname LIKE %s
            """,
            [relkind, like],
        )
        names = [row[0] for row in cursor.fetchall()]
        for name in names:
            cursor.execute(f'{statement} {quote(name)} RENAME TO {quote(new_name(name))}')
        counts[relkind] = len(names)
    return counts


def rename_custom_fields(cursor, quote, apps):
    for old, new in CUSTOM_FIELD_RENAMES.items():
        cursor.execute('SELECT id FROM extras_customfield WHERE name = %s', [old])
        row = cursor.fetchone()
        if row is None:
            continue
        cursor.execute('SELECT 1 FROM extras_customfield WHERE name = %s', [new])
        if cursor.fetchone():
            logger.warning('Custom field %s already exists; %s left as it is', new, old)
            continue
        cursor.execute('UPDATE extras_customfield SET name = %s WHERE id = %s', [new, row[0]])
        field = apps.get_model('extras', 'CustomField')._meta.get_field('object_types')
        cursor.execute(
            f"""
            SELECT ct.app_label, ct.model FROM {quote(field.m2m_db_table())} cot
            JOIN django_content_type ct ON ct.id = cot.{quote(field.m2m_reverse_name())}
            WHERE cot.{quote(field.m2m_column_name())} = %s
            """,
            [row[0]],
        )
        for app_label, model in cursor.fetchall():
            try:
                table = apps.get_model(app_label, model)._meta.db_table
            except LookupError:
                continue
            cursor.execute(
                f"""
                UPDATE {quote(table)}
                SET custom_field_data = (custom_field_data - %s) || jsonb_build_object(%s, custom_field_data -> %s)
                WHERE custom_field_data ? %s
                """,
                [old, new, old, old],
            )


def adopt(schema_editor, apps):
    global adopted
    quote = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        counts = rename_database_objects(cursor, quote)
        cursor.execute(
            'UPDATE django_content_type SET app_label = %s WHERE app_label = %s', [NEW_APP, OLD_APP]
        )
        rename_custom_fields(cursor, quote, apps)
        cursor.execute(
            """
            UPDATE users_userconfig SET data = replace(data::text, %s, %s)::jsonb
            WHERE data::text LIKE %s
            """,
            [f'"{OLD_APP}.', f'"{NEW_APP}.', f'%"{OLD_APP}.%'],
        )
        cursor.execute('DELETE FROM django_migrations WHERE app = %s', [OLD_APP])
    adopted = True
    logger.info(
        'Took over the netbox-iec62443 installation: %s tables, %s sequences, %s indexes renamed',
        counts['r'], counts['S'], counts['i'],
    )


class AdoptOrCreate(Operation):
    """Take over a netbox-iec62443 installation (see the module docstring), or run `operations` to create the
    tables. The migration state is always that of `operations`."""

    reversible = True

    def __init__(self, operations):
        self.operations = operations

    def deconstruct(self):
        return self.__class__.__qualname__, [], {'operations': self.operations}

    def state_forwards(self, app_label, state):
        for operation in self.operations:
            operation.state_forwards(app_label, state)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        with schema_editor.connection.cursor() as cursor:
            take_over = old_installation(cursor)
        if take_over:
            adopt(schema_editor, from_state.apps)
            return
        for operation in self.operations:
            state = from_state.clone()
            operation.state_forwards(app_label, state)
            operation.database_forwards(app_label, schema_editor, from_state, state)
            from_state = state

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        # As SeparateDatabaseAndState does it: undo the operations last to first, each between its own states.
        before = {}
        for index, operation in enumerate(self.operations):
            before[index] = to_state
            to_state = to_state.clone()
            operation.state_forwards(app_label, to_state)
        for index in reversed(range(len(self.operations))):
            from_state, to_state = to_state, before[index]
            self.operations[index].database_backwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return 'Take over a netbox-iec62443 installation, or create the tables'

    @property
    def migration_name_fragment(self):
        return 'initial'
