"""
Taking over a netbox-iec62443 installation (netbox_ot/adopt.py). The test database is turned into an old
installation first: the plugin's database objects get the old prefix back, the content types the old app label,
the custom fields their old names, and django_migrations the old app's rows.
"""
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase

from core.models import ObjectType
from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from extras.models import CustomField
from users.models import ObjectPermission

from netbox_ot import adopt
from netbox_ot.customfields import PURDUE_CF_NAME
from netbox_ot.models import Zone

OLD_MIGRATIONS = [
    '0001_initial', '0002_fieldbus_industrialservice', '0003_protect_zone_conduits', '0004_rename_conduit_to_flow',
    '0005_conduit_flowhop_flow_fields', '0006_split_conduits_into_flows', '0007_drop_conduit_text_and_service_ports',
    '0008_audit_layer', '0009_security_level_vectors', '0010_drop_single_security_level',
]


def make_old_installation(migrations=OLD_MIGRATIONS):
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        adopt.rename_database_objects(cursor, quote, old_prefix=adopt.NEW_PREFIX, new_prefix=adopt.OLD_PREFIX)
        cursor.execute('UPDATE django_content_type SET app_label = %s WHERE app_label = %s',
                       [adopt.OLD_APP, adopt.NEW_APP])
        for old, new in adopt.CUSTOM_FIELD_RENAMES.items():
            cursor.execute('UPDATE extras_customfield SET name = %s WHERE name = %s', [old, new])
            cursor.execute(
                """UPDATE dcim_device SET custom_field_data = (custom_field_data - %s)
                   || jsonb_build_object(%s, custom_field_data -> %s) WHERE custom_field_data ? %s""",
                [new, old, new, new],
            )
        cursor.execute('DELETE FROM django_migrations WHERE app = %s', [adopt.NEW_APP])
        for name in migrations:
            cursor.execute('INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, now())',
                           [adopt.OLD_APP, name])
    ContentType.objects.clear_cache()


def comparable(names):
    """Names cut where the round trip may have cut them: renaming to the longer old prefix truncates names to
    PostgreSQL's 63 characters (a real old installation has its own names of at most 63, which only get shorter)."""
    cut = 63 - (len(adopt.OLD_PREFIX) - len(adopt.NEW_PREFIX))
    return {name[:cut] for name in names}


def relations(prefix):
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = current_schema() AND c.relname LIKE %s""",
            [prefix.replace('_', r'\_') + '%'],
        )
        return {row[0] for row in cursor.fetchall()}


class AdoptTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Plant', slug='plant')
        maker = Manufacturer.objects.create(name='Maker', slug='maker')
        device_type = DeviceType.objects.create(manufacturer=maker, model='PLC', slug='plc')
        role = DeviceRole.objects.create(name='PLC', slug='plc')
        cls.plc = Device.objects.create(name='plc1', site=site, device_type=device_type, role=role,
                                        custom_field_data={PURDUE_CF_NAME: '1'})
        cls.zone = Zone.objects.create(name='Cell', slug='cell', site=site, purdue_level='1')
        cls.zone.devices.add(cls.plc)
        cls.permission = ObjectPermission.objects.create(name='OT viewers', actions=['view'])
        cls.permission.object_types.set([ObjectType.objects.get_for_model(Zone)])
        cls.zone_type_id = ObjectType.objects.get_for_model(Zone).pk
        cls.ot_relations = relations(adopt.NEW_PREFIX)

    def tearDown(self):
        ContentType.objects.clear_cache()

    def adopt(self):
        with connection.schema_editor() as schema_editor:
            adopt.adopt(schema_editor, apps)
        ContentType.objects.clear_cache()

    def test_no_old_installation(self):
        with connection.cursor() as cursor:
            self.assertFalse(adopt.old_installation(cursor))

    def test_old_installation_detected(self):
        make_old_installation()
        self.assertEqual(relations(adopt.NEW_PREFIX), set())
        with connection.cursor() as cursor:
            self.assertTrue(adopt.old_installation(cursor))

    def test_old_installation_not_at_last_release(self):
        make_old_installation(OLD_MIGRATIONS[:9])
        with connection.cursor() as cursor, self.assertRaisesMessage(adopt.AdoptionError, '0.2.0'):
            adopt.old_installation(cursor)

    def test_old_installation_with_development_migrations(self):
        make_old_installation(OLD_MIGRATIONS + ['0011_pluginsettings'])
        with connection.cursor() as cursor, self.assertRaisesMessage(adopt.AdoptionError, '0011_pluginsettings'):
            adopt.old_installation(cursor)

    def test_adopt(self):
        make_old_installation()
        self.adopt()
        # Same tables, indexes, sequences and constraints as a new installation, under the new names
        self.assertEqual(comparable(relations(adopt.NEW_PREFIX)), comparable(self.ot_relations))
        self.assertEqual(relations(adopt.OLD_PREFIX), set())
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_constraint WHERE conname LIKE 'netbox\\_iec62443\\_%%'")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute('SELECT count(*) FROM django_migrations WHERE app = %s', [adopt.OLD_APP])
            self.assertEqual(cursor.fetchone()[0], 0)
        # The data, its object type and what points at it survive
        zone = Zone.objects.get(pk=self.zone.pk)
        self.assertEqual(list(zone.devices.all()), [self.plc])
        self.assertEqual(ObjectType.objects.get_for_model(Zone).pk, self.zone_type_id)
        self.assertIn(self.zone_type_id, self.permission.object_types.values_list('pk', flat=True))
        # Custom fields renamed, values included
        self.assertTrue(CustomField.objects.filter(name=PURDUE_CF_NAME).exists())
        self.assertFalse(CustomField.objects.filter(name__startswith='iec62443_').exists())
        self.assertEqual(Device.objects.get(pk=self.plc.pk).custom_field_data.get(PURDUE_CF_NAME), '1')
        self.assertTrue(adopt.adopted)
        adopt.adopted = False

    def test_values_renamed_when_the_field_already_was(self):
        # A netbox-branching branch migrates after main: the field definition (main only) has the new name, the
        # branch's own copy of the device still holds the old key.
        make_old_installation()
        with connection.cursor() as cursor:
            for old, new in adopt.CUSTOM_FIELD_RENAMES.items():
                cursor.execute('UPDATE extras_customfield SET name = %s WHERE name = %s', [new, old])
        self.adopt()
        self.assertEqual(Device.objects.get(pk=self.plc.pk).custom_field_data.get(PURDUE_CF_NAME), '1')
        self.assertNotIn('iec62443_purdue_level', Device.objects.get(pk=self.plc.pk).custom_field_data)
        adopt.adopted = False

    def test_operation_takes_over_instead_of_creating(self):
        make_old_installation()
        operation = adopt.AdoptOrCreate(operations=[])
        with connection.schema_editor() as schema_editor:
            operation.database_forwards('netbox_ot', schema_editor, _State(), _State())
        ContentType.objects.clear_cache()
        self.assertEqual(comparable(relations(adopt.NEW_PREFIX)), comparable(self.ot_relations))
        adopt.adopted = False


class _State:
    apps = apps
