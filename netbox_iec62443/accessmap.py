"""
The access map: every conduit into a zone at Purdue level <= N (default 2), i.e. every
path to the controllers, with its "allowed?" verdict. Plus a small server-rendered SVG of the same.
"""
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .choices import ConduitAllowedChoices, ConduitDirectionChoices, PurdueLevelChoices
from .models import Conduit, Zone

ALLOWED_ORDER = Case(
    When(allowed=ConduitAllowedChoices.NO, then=Value(0)),
    When(allowed=ConduitAllowedChoices.UNKNOWN, then=Value(1)),
    default=Value(2),
    output_field=IntegerField(),
)


def access_map_conduits(queryset=None, site=None, max_level=PurdueLevelChoices.LEVEL_2):
    """Conduits into zones at Purdue level <= max_level (two-way conduits count from either end)."""
    levels = PurdueLevelChoices.at_or_below(max_level)
    qs = (queryset if queryset is not None else Conduit.objects.all()).select_related(
        'source_zone__site', 'destination_zone__site'
    )
    if site is not None:
        qs = qs.filter(Q(source_zone__site=site) | Q(destination_zone__site=site))
    qs = qs.filter(
        Q(destination_zone__purdue_level__in=levels) |
        Q(direction=ConduitDirectionChoices.TWO_WAY, source_zone__purdue_level__in=levels)
    )
    return qs.annotate(allowed_order=ALLOWED_ORDER).order_by(
        'allowed_order', 'destination_zone__purdue_level', 'destination_zone__name', 'name'
    )


#
# SVG diagram: one row per Purdue level (5 at the top, 0 at the bottom), zones as boxes, conduits as arrows.
#

LINE_COLORS = {'no': '#d63939', 'unknown': '#f59f00', 'yes': '#2fb344'}
BOX_W, BOX_H, GAP_X, ROW_H, LABEL_W, PAD = 190, 46, 40, 96, 150, 16


def _level_rows(zones):
    order = [None] + [value for value, _label in reversed(PurdueLevelChoices.CHOICES)]
    labels = {value: str(label).split(' (')[0] for value, label in PurdueLevelChoices.CHOICES}
    labels[None] = str(_('No level'))
    rows = []
    for level in order:
        members = sorted((z for z in zones if (z.purdue_level or None) == level), key=lambda z: z.name)
        if members:
            rows.append((labels[level], members))
    return rows


def access_map_svg(conduits, zones=()):
    """Return an inline SVG (safe string) for the given conduits; `zones` adds zones without conduits."""
    conduits = list(conduits)
    all_zones = {z.pk: z for z in zones}
    for c in conduits:
        all_zones.setdefault(c.source_zone_id, c.source_zone)
        all_zones.setdefault(c.destination_zone_id, c.destination_zone)
    if not all_zones:
        return ''
    rows = _level_rows(all_zones.values())
    width = LABEL_W + max(len(m) for _l, m in rows) * (BOX_W + GAP_X) + PAD
    height = len(rows) * ROW_H + PAD
    pos = {}
    out, lines, badges = [], [], []
    for r, (label, members) in enumerate(rows):
        y = PAD + r * ROW_H
        out.append(f'<text x="8" y="{y + BOX_H / 2 + 4}" class="lvl">{escape(label)}</text>')
        out.append(f'<line x1="0" x2="{width}" y1="{y + ROW_H - 25}" y2="{y + ROW_H - 25}" class="sep"/>')
        for i, z in enumerate(members):
            x = LABEL_W + i * (BOX_W + GAP_X)
            pos[z.pk] = (x, y)
            out.append(
                f'<a href="{escape(z.get_absolute_url())}"><rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" '
                f'rx="4" class="zone"/><text x="{x + BOX_W / 2}" y="{y + BOX_H / 2 + 4}" text-anchor="middle" '
                f'class="zn">{escape(z.name[:26])}</text></a>'
            )
    pair_seen = {}
    for n, c in enumerate(conduits, start=1):
        (sx, sy), (dx, dy) = pos[c.source_zone_id], pos[c.destination_zone_id]
        key = tuple(sorted((c.source_zone_id, c.destination_zone_id)))
        offset = pair_seen.get(key, 0) * 14
        pair_seen[key] = pair_seen.get(key, 0) + 1
        x1, x2 = sx + BOX_W / 2 + offset, dx + BOX_W / 2 + offset
        if sy == dy:  # same row: arc above the boxes
            y1 = y2 = sy
            mid_y = sy - 22 - offset
            path = f'M{x1},{y1} Q{(x1 + x2) / 2},{mid_y - 20} {x2},{y2}'
            lx, ly = (x1 + x2) / 2, mid_y - 8
        else:
            y1 = sy + BOX_H if sy < dy else sy
            y2 = dy if sy < dy else dy + BOX_H
            path = f'M{x1},{y1} L{x2},{y2}'
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
        color = LINE_COLORS.get(c.allowed, '#888')
        dash = ' stroke-dasharray="6 4"' if c.remote_access else ''
        start = ' marker-start="url(#iec-arrow)"' if c.direction == ConduitDirectionChoices.TWO_WAY else ''
        lines.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"{dash}{start} '
            f'marker-end="url(#iec-arrow)"><title>{escape(c.name)}</title></path>'
        )
        badges.append(
            f'<circle cx="{lx}" cy="{ly}" r="10" fill="{color}"/>'
            f'<text x="{lx}" y="{ly + 4}" text-anchor="middle" class="num">{n}</text>'
        )
    aria = escape(_('Access map diagram'))
    svg = (
        f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
        f'aria-label="{aria}" class="iec62443-map">'
        '<defs>'
        '<marker id="iec-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker>'
        '</defs>'
        '<style>.iec62443-map .zone{fill:var(--tblr-bg-surface,#fff);stroke:rgba(32,107,196,.7);stroke-width:1.5}'
        '.iec62443-map .zn{fill:currentColor;font-size:13px;font-weight:600}'
        '.iec62443-map .lvl{fill:currentColor;opacity:.7;font-size:12px}'
        '.iec62443-map .sep{stroke:currentColor;opacity:.12}'
        '.iec62443-map .num{fill:#fff;font-size:11px;font-weight:700}</style>'
        + ''.join(lines + out + badges) + '</svg>'
    )
    return mark_safe(svg)


def site_zones(site):
    return Zone.objects.filter(site=site) if site is not None else Zone.objects.none()
