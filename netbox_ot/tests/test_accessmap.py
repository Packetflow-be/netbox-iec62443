from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse

from dcim.models import Site
from utilities.testing import TestCase

from netbox_ot import demo_large
from netbox_ot.accessdiagram import BOX_W, PER_ROW, _graph, _layout, access_map_diagram
from netbox_ot.accessmap import access_map_flows
from netbox_ot.models import Flow, Zone


class AccessMapPlant(TestCase):
    """Office (4) above a DMZ (3.5), a control room (2) and a cell (1) with a sub-zone."""
    user_permissions = ('netbox_ot.view_flow', 'netbox_ot.view_zone', 'dcim.view_site')

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')

        def zone(name, level, **kwargs):
            return Zone.objects.create(name=name, slug=name.lower().replace(' ', '-'), site=cls.site,
                                       purdue_level=level, **kwargs)

        cls.office, cls.dmz, cls.room, cls.cell = zone('Office', '4'), zone('DMZ', '3.5'), zone('Room', '2'), \
            zone('Cell', '1')
        cls.robots = zone('Robots', '1', parent=cls.cell)
        cls.spare = zone('Spare', '1')

        def flow(src, dst, name, **kwargs):
            return Flow.objects.create(source_zone=src, destination_zone=dst, name=name, **kwargs)

        cls.blocked = flow(cls.office, cls.cell, 'office to cell', allowed='no', protocol='modbus-tcp')
        cls.remote = flow(cls.office, cls.cell, 'vendor', allowed='yes', protocol='rdp', remote_access=True)
        cls.control = flow(cls.room, cls.cell, 'control', allowed='yes', protocol='s7comm')
        cls.inside = flow(cls.cell, cls.robots, 'cell to robots', allowed='yes', protocol='profinet')
        cls.unknown = flow(cls.dmz, cls.room, 'dmz to room', protocol='opc-ua', connection='reverse-connect')


class AccessMapFilterTest(AccessMapPlant):

    def _names(self, **filters):
        return [f.name for f in access_map_flows(site=self.site, max_level='5', **filters)]

    def test_filters(self):
        self.assertEqual(len(self._names()), 5)
        self.assertEqual(self._names(verdict=['no']), ['office to cell'])
        self.assertEqual(self._names(verdict=['no', 'unknown']), ['office to cell', 'dmz to room'])
        self.assertEqual(self._names(protocol=['s7comm', 'profinet']), ['control', 'cell to robots'])
        self.assertEqual(self._names(connection=['reverse-connect']), ['dmz to room'])
        self.assertEqual(self._names(remote_access=True), ['vendor'])
        self.assertEqual(len(self._names(remote_access=False)), 4)
        # A zone and its neighbours
        self.assertEqual(self._names(zones=[self.room]), ['dmz to room', 'control'])

    def test_expired_is_its_own_verdict(self):
        Flow.objects.filter(pk=self.remote.pk).update(expires='2020-01-01')
        self.assertEqual(self._names(verdict=['expired']), ['vendor'])
        self.assertNotIn('vendor', self._names(verdict=['yes']))


class AccessMapDiagramTest(AccessMapPlant):

    def _flows(self):
        return list(access_map_flows(site=self.site, max_level='5'))

    def test_one_arrow_per_zone_pair(self):
        diagram = access_map_diagram(self._flows())
        self.assertEqual((diagram['zones'], diagram['arrows']), (5, 4))
        edge = diagram['data']['edges'][f'{self.office.pk}-{self.cell.pk}']
        self.assertEqual([f['verdict'] for f in edge['flows']], ['no', 'yes'])
        self.assertTrue(edge['flows'][1]['remote'])
        # Both verdicts are counted on the arrow, and the sub-zone names its parent
        self.assertIn('class="ot-badge"', diagram['svg'])
        self.assertIn('in Cell', diagram['svg'])
        self.assertNotIn('Spare', diagram['svg'])
        self.assertIn('Spare', access_map_diagram(self._flows(), Zone.objects.filter(site=self.site))['svg'])

    def test_arrows_pass_between_zones(self):
        # Office to Cell skips two rows: its waypoints there keep clear of the zones of those rows
        nodes, edges = _graph(self._flows(), (), False, Zone.objects.all())
        rows, x = _layout(nodes, edges, PER_ROW)
        waypoints = [item for row in rows for item in row['items'] if item[0] == 'd']
        self.assertEqual(len(waypoints), 2)
        for row in rows:
            boxes = [x[item] for item in row['items'] if item[0] == 'n']
            for item in row['items']:
                if item[0] == 'd':
                    self.assertTrue(all(abs(x[item] - box) > BOX_W / 2 for box in boxes))

    def test_collapse(self):
        diagram = access_map_diagram(self._flows(), collapse=True)
        self.assertEqual((diagram['zones'], diagram['arrows']), (4, 3))
        cell = diagram['data']['nodes'][str(self.cell.pk)]
        self.assertEqual([z['name'] for z in cell['members']], ['Robots'])
        self.assertEqual([f['name'] for f in cell['inside']], ['cell to robots'])
        self.assertIn('+1 sub-zone', diagram['svg'])

    def test_a_level_wraps(self):
        for n in range(8):
            zone = Zone.objects.create(name=f'Cell {n}', slug=f'cell-{n}', site=self.site, purdue_level='1')
            Flow.objects.create(source_zone=self.room, destination_zone=zone, name=f'to {n}')
        nodes, edges = _graph(self._flows(), (), False, Zone.objects.all())
        rows, _x = _layout(nodes, edges, PER_ROW)
        level_1 = [row for row in rows if row['level'] == '1']
        self.assertEqual(len(level_1), 2)
        self.assertTrue(all(sum(1 for item in row['items'] if item[0] == 'n') <= PER_ROW for row in level_1))

    def test_empty(self):
        self.assertEqual(access_map_diagram([])['svg'], '')


class AccessMapPageTest(AccessMapPlant):

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_site_tab_filters(self):
        url = reverse('dcim:site_ot_accessmap', kwargs={'pk': self.site.pk})
        response = self.client.get(url)
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'ot-map-data')
        self.assertContains(response, 'netbox_ot/accessmap.js')
        self.assertContains(response, 'office to cell')
        response = self.client.get(f'{url}?max_level=5&verdict=unknown&collapse=on')
        self.assertHttpStatus(response, 200)
        self.assertEqual([f.name for f in response.context['flows']], ['dmz to room'])
        self.assertEqual(response.context['flows_total'], 5)
        self.assertContains(response, 'of 5, filtered')
        # A box of the collapsed diagram stands for its sub-zones too
        response = self.client.get(f'{url}?max_level=5&collapse=on&zone_id={self.cell.pk}')
        self.assertEqual(len(response.context['flows']), 4)
        response = self.client.get(f'{url}?verdict=nonsense')
        self.assertHttpStatus(response, 200)

    @override_settings(EXEMPT_VIEW_PERMISSIONS=[])
    def test_no_diagram_for_all_sites(self):
        response = self.client.get(reverse('plugins:netbox_ot:accessmap') + '?max_level=5')
        self.assertHttpStatus(response, 200)
        self.assertContains(response, 'Choose a site to see its diagram')
        self.assertNotContains(response, '<svg')
        self.assertEqual(len(response.context['flows']), 5)


class LargeDemoTest(TestCase):

    def test_create_and_delete(self):
        out = StringIO()
        call_command('ot_demo', '--large', stdout=out)
        self.assertIn('35 zones', out.getvalue())
        site = Site.objects.get(slug=demo_large.SITE_SLUG)
        self.assertEqual(Zone.objects.count(), 35)
        self.assertGreaterEqual(Flow.objects.count(), 180)
        self.assertFalse(Site.objects.filter(slug='iec62443-demo').exists())
        diagram = access_map_diagram(access_map_flows(site=site, max_level='5'))
        self.assertGreater(diagram['arrows'], 80)
        self.assertLess(access_map_diagram(access_map_flows(site=site, max_level='5'), collapse=True)['zones'],
                        diagram['zones'])
        with self.assertRaisesRegex(CommandError, 'already exists'):
            call_command('ot_demo', '--large', stdout=StringIO())
        call_command('ot_demo', '--large', '--delete', stdout=StringIO())
        self.assertEqual((Zone.objects.count(), Flow.objects.count(), Site.objects.count()), (0, 0, 0))
