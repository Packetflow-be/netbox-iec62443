"""
The access map diagram: a server-rendered SVG, so it prints and works without JavaScript; the page's script
(static/netbox_ot/accessmap.js) adds zoom, pan, highlighting and the detail panel on top of it.

Purdue levels are the rows (5 at the top, 0 at the bottom); a level with many zones wraps into several rows.
There is one arrow per directed zone pair. An arrow that skips rows is routed through the gaps between the
zones of the rows in between, never behind a zone, and the zones of a row are ordered so that arrows cross as
little as possible (a layered layout: long arrows get a waypoint in every row they pass, and rows are sorted by
the mean position of their neighbours a few times over).
"""
import math
from collections import defaultdict

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .choices import ConnectionChoices, PurdueLevelChoices, ZoneTypeChoices
from .exposure import changes_flow

WORST = ('no', 'expired', 'unknown', 'yes')
# Three colours on the diagram: not allowed and expired are both red
SHADE = {'no': 'red', 'expired': 'red', 'unknown': 'amber', 'yes': 'green'}
SHADES = ('red', 'amber', 'green')
COLORS = {'red': '#d63939', 'amber': '#f59f00', 'green': '#2fb344'}

BOX_W, BOX_H = 172, 46
GAP_X = 26          # between two zones of a row
LANE = 13           # between two arrows passing a row side by side
GAP_Y = 86          # between two rows
LABEL_W, PAD = 150, 18
PER_ROW = 6         # zones per row before a Purdue level wraps


class Node:
    """A box: one zone, or a top-level zone with its sub-zones collapsed into it."""

    def __init__(self, key, zone):
        self.key, self.zone = key, zone
        self.members = []    # sub-zones collapsed into this box
        self.inside = []     # flows between the zones of this box
        self.parent_name = ''
        self.layer = self.x = self.y = 0
        self.top, self.bottom = [], []

    @property
    def level(self):
        return self.zone.purdue_level or None


class Edge:
    """All flows from one box to another."""

    def __init__(self, src, dst):
        self.src, self.dst = src, dst
        self.flows = []
        self.chain = []

    @property
    def key(self):
        return f'{self.src}-{self.dst}'


def _verdict(flow):
    return 'expired' if flow.is_expired else flow.allowed


def _flow_title(flow):
    if flow.connection == ConnectionChoices.BROKERED and flow.broker_zone_id:
        return _('{flow} (through a broker in {zone})').format(flow=flow, zone=flow.broker_zone)
    if flow.connection != ConnectionChoices.CLIENT_SERVER:
        return f'{flow} ({flow.get_connection_display().lower()})'
    return str(flow)


def _short(text, length):
    return text if len(text) <= length else text[:length - 1].rstrip() + '…'


def _graph(flows, zones, collapse, zone_queryset):
    """Boxes and arrows for these flows; `zones` adds zones without flows."""
    known = {z.pk: z for z in zones}
    for f in flows:
        known.setdefault(f.source_zone_id, f.source_zone)
        known.setdefault(f.destination_zone_id, f.destination_zone)
    if not known:
        return {}, {}
    # Parents: one query for the parent of every zone, one for the parents that are not on the map themselves
    parents = {}
    if any(z.parent_id for z in known.values()):
        parents = dict(zone_queryset.values_list('pk', 'parent_id'))
    box = {}
    if collapse:
        for pk in known:
            top, seen = pk, {pk}
            while parents.get(top) and parents[top] in parents and parents[top] not in seen:
                top = parents[top]
                seen.add(top)
            box[pk] = top
    else:
        box = {pk: pk for pk in known}
    wanted = set(box.values()) | {z.parent_id for z in known.values() if z.parent_id}
    missing = wanted - set(known)
    extra = zone_queryset.in_bulk(missing) if missing else {}
    nodes = {}
    for pk, zone in known.items():
        key = box[pk]
        if key not in nodes:
            nodes[key] = Node(key, known.get(key) or extra[key])
        if key != pk:
            nodes[key].members.append(zone)
        elif zone.parent_id:
            parent = known.get(zone.parent_id) or extra.get(zone.parent_id)
            nodes[key].parent_name = parent.name if parent else ''
    edges = {}
    for f in flows:
        src, dst = box[f.source_zone_id], box[f.destination_zone_id]
        if src == dst:
            nodes[src].inside.append(f)
            continue
        edges.setdefault((src, dst), Edge(src, dst)).flows.append(f)
    return nodes, edges


def _layout(nodes, edges, per_row):
    """Give every box a row and a position, and every arrow its waypoints. Returns (rows, x of every item)."""
    order = [None] + [value for value, _label in reversed(PurdueLevelChoices.CHOICES)]
    labels = {value: str(label).split(' (')[0] for value, label in PurdueLevelChoices.CHOICES}
    labels[None] = str(_('No level'))
    rows = []
    for level in order:
        members = sorted((n for n in nodes.values() if n.level == level),
                         key=lambda n: (n.parent_name or n.zone.name, bool(n.parent_name), n.zone.name))
        if not members:
            continue
        count = math.ceil(len(members) / per_row)
        size = math.ceil(len(members) / count)
        for r in range(count):
            for n in members[r * size:(r + 1) * size]:
                n.layer = len(rows)
            rows.append({'level': level, 'label': labels[level], 'first': r == 0,
                         'items': [('n', n.key) for n in members[r * size:(r + 1) * size]]})

    # An arrow that skips rows gets a waypoint in each of them; `up` and `down` are an item's neighbours in the
    # row above and below
    up, down = defaultdict(list), defaultdict(list)
    for e in edges.values():
        a, b = nodes[e.src].layer, nodes[e.dst].layer
        step = 1 if b > a else -1
        between = [('d', e.src, e.dst, i) for i in range(a + step, b, step)] if a != b else []
        for item in between:
            rows[item[3]]['items'].append(item)
        e.chain = [('n', e.src), *between, ('n', e.dst)]
        if a == b:
            continue
        for p, q in zip(e.chain, e.chain[1:]):
            (down if step == 1 else up)[p].append(q)
            (up if step == 1 else down)[q].append(p)

    # Fewer crossings: sort each row by the mean position of its neighbours in the row before, downwards and
    # upwards in turn. Items without neighbours stay where they are.
    index = {}
    for row in rows:
        index.update({item: i for i, item in enumerate(row['items'])})
    for _sweep in range(4):
        for sequence, neighbours in ((rows[1:], up), (rows[-2::-1], down)):
            for row in sequence:
                items = row['items']
                mean = {it: sum(index[n] for n in neighbours[it]) / len(neighbours[it])
                        for it in items if neighbours.get(it)}
                moving = iter(sorted(mean, key=lambda it: (mean[it], index[it])))
                row['items'] = [next(moving) if it in mean else it for it in items]
                index.update({item: i for i, item in enumerate(row['items'])})

    def gap(a, b):
        if a[0] == 'n' and b[0] == 'n':
            return BOX_W + GAP_X
        return LANE if a[0] == b[0] else BOX_W / 2 + LANE + 4

    # Positions: packed and centred first, then pulled towards the neighbours (the mean of what a pass from the
    # left and a pass from the right allow), which straightens the arrows
    x = {}
    for row in rows:
        at = 0
        for i, item in enumerate(row['items']):
            at += gap(row['items'][i - 1], item) if i else 0
            x[item] = at
        for item in row['items']:
            x[item] -= at / 2
    for _pass in range(3):
        for sequence, neighbours in ((rows[1:], up), (rows[-2::-1], down)):
            for row in sequence:
                items = row['items']
                want = [sum(x[n] for n in neighbours[it]) / len(neighbours[it]) if neighbours.get(it) else x[it]
                        for it in items]
                left, right = list(want), list(want)
                for i in range(1, len(items)):
                    left[i] = max(want[i], left[i - 1] + gap(items[i - 1], items[i]))
                for i in range(len(items) - 2, -1, -1):
                    right[i] = min(want[i], right[i + 1] - gap(items[i], items[i + 1]))
                for i, item in enumerate(items):
                    x[item] = (left[i] + right[i]) / 2
    low = min(v - (BOX_W / 2 if item[0] == 'n' else LANE) for item, v in x.items())
    for item in x:
        x[item] = round(x[item] - low + LABEL_W, 1)
    return rows, x


def _point(p0, p1, p2, p3, t):
    u = 1 - t
    return tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3))


def _flow_data(flow):
    return {
        'name': str(flow),
        'url': flow.get_absolute_url(),
        'verdict': _verdict(flow),
        'protocol': flow.get_protocol_display() if flow.protocol else '',
        'ports': flow.ports_short,
        'connection': '' if flow.connection == ConnectionChoices.CLIENT_SERVER else flow.get_connection_display(),
        'remote': flow.remote_access,
        'changes': changes_flow(flow),
    }


def access_map_diagram(flows, zones=(), collapse=False, zone_queryset=None, per_row=PER_ROW):
    """
    The diagram for these flows as {'svg': safe string, 'data': what the page's script needs, 'zones': number of
    boxes, 'arrows': number of arrows}; `zones` adds zones without flows, `collapse` draws sub-zones inside
    their top-level zone. `zone_queryset` is what the viewer may see of the zones (for the parents).
    """
    from .models import Zone

    flows = list(flows)
    nodes, edges = _graph(flows, zones, collapse, zone_queryset if zone_queryset is not None else Zone.objects.all())
    if not nodes:
        return {'svg': '', 'data': {}, 'zones': 0, 'arrows': 0}
    rows, x = _layout(nodes, edges, per_row)

    # Rows top to bottom; a row with arrows between its own zones gets room above it for their arcs
    arcs = defaultdict(list)
    for e in edges.values():
        if nodes[e.src].layer == nodes[e.dst].layer:
            arcs[nodes[e.src].layer].append(e)
    position = {item: i for row in rows for i, item in enumerate(row['items'])}

    def arc_height(e):
        return 20 + 9 * min(abs(position[('n', e.src)] - position[('n', e.dst)]), 5)

    y = PAD
    for i, row in enumerate(rows):
        row['room'] = max((arc_height(e) + 8 for e in arcs[i]), default=0)
        y += (GAP_Y if i else 0) + row['room']
        row['y'] = y
        y += BOX_H
    height = y + PAD
    width = max(v + (BOX_W / 2 if item[0] == 'n' else LANE) for item, v in x.items()) + PAD
    for n in nodes.values():
        n.x, n.y = x[('n', n.key)], rows[n.layer]['y']

    # Where the arrows touch a box: spread over its top or bottom edge, ordered by where the other end is, so
    # they do not share a line. Arcs within a row take the outer places so that they nest instead of crossing.
    for e in edges.values():
        src, dst = nodes[e.src], nodes[e.dst]
        after, before = x[e.chain[1]], x[e.chain[-2]]
        if src.layer == dst.layer:
            src.top.append(((2 if after > src.x else 0, -after), e.key, 'src'))
            dst.top.append(((2 if before > dst.x else 0, -before), e.key, 'dst'))
        else:
            (src.bottom if dst.layer > src.layer else src.top).append(((1, after), e.key, 'src'))
            (dst.top if dst.layer > src.layer else dst.bottom).append(((1, before), e.key, 'dst'))
    port = {}
    for n in nodes.values():
        for side, at in ((n.top, n.y), (n.bottom, n.y + BOX_H)):
            side.sort()
            step = min(16, (BOX_W - 28) / max(len(side) - 1, 1))
            for i, (_order, key, end) in enumerate(side):
                port[(key, end)] = (round(n.x + (i - (len(side) - 1) / 2) * step, 1), at, i)

    out = []
    # Bands: the label of each Purdue level, a line between two levels
    for i, row in enumerate(rows):
        if row['first']:
            if i:
                line = row['y'] - row['room'] - GAP_Y / 2
                out.append(f'<line x1="0" x2="{width}" y1="{line}" y2="{line}" class="sep"/>')
            out.append(f'<text x="8" y="{row["y"] + BOX_H / 2 + 4}" class="lvl">{escape(row["label"])}</text>')

    lines, badges, placed = [], [], []
    for e in sorted(edges.values(), key=lambda e: -min(WORST.index(_verdict(f)) for f in e.flows)):
        src, dst = nodes[e.src], nodes[e.dst]
        (x1, y1, _i), (x2, y2, place) = port[(e.key, 'src')], port[(e.key, 'dst')]
        if src.layer == dst.layer:
            h = arc_height(e)
            last = ((x1, y1), (x1, y1 - h * 4 / 3), (x2, y2 - h * 4 / 3), (x2, y2))
            path = f'M{x1},{y1} C{x1},{last[1][1]:.1f} {x2},{last[2][1]:.1f} {x2},{y2}'
            choices = (0.5, 0.36, 0.64)
        else:
            down = dst.layer > src.layer
            points = [(x1, y1)]
            for item in e.chain[1:-1]:
                top, bottom = rows[item[3]]['y'] - 10, rows[item[3]]['y'] + BOX_H + 10
                points += [(x[item], top), (x[item], bottom)] if down else [(x[item], bottom), (x[item], top)]
            points.append((x2, y2))
            path = f'M{x1},{y1}'
            for (ax, ay), (cx, cy) in zip(points, points[1:]):
                last = ((ax, ay), (ax, (ay + cy) / 2), (cx, (ay + cy) / 2), (cx, cy))
                path += f' C{ax},{last[1][1]:.1f} {cx},{last[2][1]:.1f} {cx},{cy}'
            # The counts sit on the last stretch, staggered so that arrows into one zone do not stack them
            choices = ((0.5, 0.34, 0.66, 0.2, 0.8) * 2)[place % 3:][:5]
        # The counts go where no other arrow's counts are yet
        spots = [_point(*last, t) for t in choices]
        bx, by = max(spots, key=lambda s: min(
            (max(abs(s[0] - px) / 2, abs(s[1] - py)) for px, py in placed), default=99) >= 19)
        if len(e.flows) > 1:
            placed.append((bx, by))
        counts = defaultdict(int)
        for f in e.flows:
            counts[SHADE[_verdict(f)]] += 1
        shade = next(s for s in SHADES if counts[s])
        # Dashed: remote access. Dotted: no inbound connection (reverse connect or a broker). Both: dash-dot.
        remote = any(f.remote_access for f in e.flows)
        outbound = any(f.is_outbound_only for f in e.flows)
        pattern = {(True, False): '6 4', (False, True): '2 4', (True, True): '6 3 2 3'}.get((remote, outbound))
        dash = f' stroke-dasharray="{pattern}"' if pattern else ''
        thick = round(1.6 + 0.3 * min(len(e.flows), 6), 1)
        # Heavy: a flow on this arrow writes, controls or programs its destination (the widest otherwise is 3.4)
        if any(changes_flow(f) for f in e.flows):
            thick = 4.5
        title = escape('\n'.join(_flow_title(f) for f in e.flows))
        attrs = f'data-edge="{e.key}" data-src="{e.src}" data-dst="{e.dst}"'
        lines.append(
            f'<g class="ot-edge" {attrs}><title>{title}</title>'
            f'<path d="{path}" class="hit"/>'
            f'<path d="{path}" class="ln" stroke="{COLORS[shade]}" stroke-width="{thick}"{dash} '
            f'marker-end="url(#ot-arrow-{shade})"/></g>'
        )
        if len(e.flows) == 1:
            continue  # one flow: the colour of the arrow says it all
        parts = [(s, counts[s]) for s in SHADES if counts[s]]
        widths = [16 if n < 10 else 22 if n < 100 else 28 for _s, n in parts]
        at = bx - sum(widths) / 2
        badge = f'<g class="ot-badge" {attrs}><title>{title}</title>'
        badge += (f'<rect x="{at - 1.5:.1f}" y="{by - 9.5:.1f}" width="{sum(widths) + 3}" height="19" rx="5" '
                  f'class="halo"/>')
        for (s, n), w in zip(parts, widths):
            badge += (f'<rect x="{at:.1f}" y="{by - 8:.1f}" width="{w}" height="16" rx="3" fill="{COLORS[s]}"/>'
                      f'<text x="{at + w / 2:.1f}" y="{by + 4:.1f}" text-anchor="middle" class="num">{n}</text>')
            at += w
        badges.append(badge + '</g>')

    types = dict(ZoneTypeChoices.CHOICES)
    for n in nodes.values():
        left, zone = n.x - BOX_W / 2, n.zone
        notes = []
        if zone.zone_type != ZoneTypeChoices.OT:
            notes.append(str(types.get(zone.zone_type, zone.zone_type)).split(' (')[0])
        if n.parent_name:
            notes.append(_('in {zone}').format(zone=_short(n.parent_name, 16)))
        if n.members:
            notes.append(ngettext('+{n} sub-zone', '+{n} sub-zones', len(n.members)).format(n=len(n.members)))
        if n.inside:
            notes.append(ngettext('{n} flow inside', '{n} flows inside', len(n.inside)).format(n=len(n.inside)))
        note = _short(', '.join(notes), 30)
        stack = (f'<rect x="{left + 4}" y="{n.y + 4}" width="{BOX_W}" height="{BOX_H}" rx="4" class="zone"/>'
                 if n.members else '')
        out.append(
            f'<g class="ot-node" data-node="{n.key}"><title>{escape(zone.name)}</title>{stack}'
            f'<a href="{escape(zone.get_absolute_url())}">'
            f'<rect x="{left}" y="{n.y}" width="{BOX_W}" height="{BOX_H}" rx="4" class="zone"/>'
            f'<text x="{n.x}" y="{n.y + (20 if note else 28)}" text-anchor="middle" class="zn">'
            f'{escape(_short(zone.name, 22))}</text>'
            + (f'<text x="{n.x}" y="{n.y + 36}" text-anchor="middle" class="zs">{escape(note)}</text>' if note else '')
            + '</a></g>'
        )

    markers = ''.join(
        f'<marker id="ot-arrow-{s}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" '
        f'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,1 L10,5 L0,9 z" fill="{c}"/></marker>'
        for s, c in COLORS.items()
    )
    width, height = math.ceil(width), math.ceil(height)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
        f'style="max-width:{width}px" role="img" aria-label="{escape(_("Access map diagram"))}" class="ot-map" '
        f'data-width="{width}" data-height="{height}">'
        f'<defs>{markers}</defs>'
        '<style>.ot-map{font-family:inherit}'
        '.ot-map .zone{fill:var(--tblr-bg-surface,#fff);stroke:rgba(32,107,196,.75);stroke-width:1.5}'
        '.ot-map .zn{fill:currentColor;font-size:13px;font-weight:600}'
        '.ot-map .zs{fill:currentColor;opacity:.65;font-size:10.5px}'
        '.ot-map .lvl{fill:currentColor;opacity:.7;font-size:12px}'
        '.ot-map .sep{stroke:currentColor;opacity:.14}'
        '.ot-map .ln{fill:none}.ot-map .hit{fill:none;stroke:transparent;stroke-width:12}'
        '.ot-map .halo{fill:var(--tblr-bg-surface,#fff);opacity:.85}'
        '.ot-map .num{fill:#fff;font-size:11px;font-weight:700}'
        '.ot-map.ot-dim .ot-edge:not(.ot-hl),.ot-map.ot-dim .ot-badge:not(.ot-hl),'
        '.ot-map.ot-dim .ot-node:not(.ot-hl){opacity:.13}'
        '.ot-map .ot-node.ot-sel .zone{stroke-width:3}'
        '.ot-map .ot-edge,.ot-map .ot-badge,.ot-map .ot-node{cursor:pointer}</style>'
        + ''.join(lines + out + badges) + '</svg>'
    )
    data = {
        'nodes': {
            str(n.key): {
                'name': n.zone.name,
                'url': n.zone.get_absolute_url(),
                'id': n.zone.pk,
                'members': [{'name': z.name, 'url': z.get_absolute_url()} for z in n.members],
                'inside': [_flow_data(f) for f in n.inside],
            } for n in nodes.values()
        },
        'edges': {e.key: {'src': str(e.src), 'dst': str(e.dst), 'flows': [_flow_data(f) for f in e.flows]}
                  for e in edges.values()},
    }
    return {'svg': mark_safe(svg), 'data': data, 'zones': len(nodes), 'arrows': len(edges)}


def access_map_svg(flows, zones=(), **kwargs):
    """The diagram alone, as an inline SVG (safe string)."""
    return access_map_diagram(flows, zones, **kwargs)['svg']
