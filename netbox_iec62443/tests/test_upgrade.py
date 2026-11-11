from types import SimpleNamespace

from django.test import TestCase

from core.models import ObjectType
from dcim.models import Site
from extras.models import CachedValue
from users.models import ObjectPermission

from netbox_iec62443.models import Conduit, Flow, FlowHop, RiskAssessment, Zone
from netbox_iec62443.upgrade import after_upgrade, data_migration_ran


def plan(*names, app_label='netbox_iec62443', backwards=False):
    return [(SimpleNamespace(app_label=app_label, name=name), backwards) for name in names]


UPGRADE = plan('0005_conduit_flowhop_flow_fields', '0006_split_conduits_into_flows')


class AfterUpgradeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name='Plant', slug='plant')
        zones = [Zone.objects.create(name=name, slug=name.lower(), site=site) for name in ('Cell', 'Office')]
        cls.conduit = Conduit.objects.create(name='Cell - Office', site=site)
        cls.conduit.zones.set(zones)
        cls.flow_type = ObjectType.objects.get_for_model(Flow)
        cls.new_types = {ObjectType.objects.get_for_model(Conduit).pk, ObjectType.objects.get_for_model(FlowHop).pk}

    def permission(self, name, *object_types, constraints=None):
        permission = ObjectPermission.objects.create(name=name, actions=['view', 'change'], constraints=constraints)
        permission.object_types.set(object_types)
        return permission

    @staticmethod
    def types(permission):
        return set(permission.object_types.values_list('pk', flat=True))

    def conduit_entries(self):
        return CachedValue.objects.filter(
            object_type=ObjectType.objects.get_for_model(Conduit), object_id=self.conduit.pk
        )

    def test_only_after_the_data_migration(self):
        self.assertTrue(data_migration_ran(UPGRADE))
        self.assertFalse(data_migration_ran(None))
        self.assertFalse(data_migration_ran([]))
        self.assertFalse(data_migration_ran(plan('0008_audit_layer')))
        self.assertFalse(data_migration_ran(plan('0006_split_conduits_into_flows', backwards=True)))
        self.assertFalse(data_migration_ran(plan('0006_something', app_label='other_plugin')))

        permission = self.permission('Flows', self.flow_type)
        self.conduit_entries().delete()
        after_upgrade(plan=plan('0008_audit_layer'))
        self.assertFalse(self.conduit_entries().exists())
        self.assertEqual(self.types(permission), {self.flow_type.pk})

    def test_search_index_rebuilt(self):
        self.conduit_entries().delete()
        after_upgrade(plan=UPGRADE)
        self.assertTrue(self.conduit_entries().filter(value='Cell - Office').exists())
        # Twice gives the same index, not doubled entries
        count = self.conduit_entries().count()
        after_upgrade(plan=UPGRADE)
        self.assertEqual(self.conduit_entries().count(), count)

    def test_flow_permissions_cover_conduits_and_hops(self):
        zone_type = ObjectType.objects.get_for_model(Zone)
        flows = self.permission('Flows', self.flow_type, zone_type)
        zones_only = self.permission('Zones', zone_type)
        constrained = self.permission('Remote flows', self.flow_type, constraints={'remote_access': True})
        after_upgrade(plan=UPGRADE)

        self.assertEqual(self.types(flows), {self.flow_type.pk, zone_type.pk} | self.new_types)
        self.assertEqual(flows.actions, ['view', 'change'])
        self.assertEqual(self.types(zones_only), {zone_type.pk})
        self.assertEqual(self.types(constrained), {self.flow_type.pk})
        # Risk assessments are new: nobody had a right on them before
        risk = ObjectType.objects.get_for_model(RiskAssessment)
        self.assertFalse(ObjectPermission.objects.filter(object_types=risk).exists())
