"""
The access map: every flow into a zone at Purdue level <= N (default 2), i.e. every path to the controllers, with
its "allowed?" verdict. Not allowed first, then allowed-but-expired, unknown, and allowed. Plus a small
server-rendered SVG with one arrow per directed zone pair.
"""
import datetime

from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .choices import FlowAllowedChoices, PurdueLevelChoices
from .models import Flow, Zone, stale_after_days


def verdict_order():
    """0 not allowed, 1 allowed but expired, 2 unknown, 3 allowed."""
    return Case(
        When(allowed=FlowAllowedChoices.NO, then=Value(0)),
        When(allowed=FlowAllowedChoices.YES, expires__lt=timezone.localdate(), then=Value(1)),
        When(allowed=FlowAllowedChoices.UNKNOWN, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )


def access_map_flows(queryset=None, site=None, max_level=PurdueLevelChoices.LEVEL_2):
    """Flows into zones at Purdue level <= max_level, from any zone of the site or into one."""
    levels = PurdueLevelChoices.at_or_below(max_level)
    qs = (queryset if queryset is not None else Flow.objects.all()).select_related(
        'source_zone__site', 'destination_zone__site', 'conduit',
    ).prefetch_related('hops__device', 'hops__virtual_machine', 'hops__tunnel')
    if site is not None:
        qs = qs.filter(Q(source_zone__site=site) | Q(destination_zone__site=site))
    qs = qs.filter(destination_zone__purdue_level__in=levels)
    return qs.annotate(verdict_order=verdict_order()).order_by(
        'verdict_order', 'destination_zone__purdue_level', 'destination_zone__name', 'name'
    )


def attention(queryset):
    """Counts of flows that need a person: allowed but expired, review due, not seen for a while, no conduit."""
    today = timezone.localdate()
    stale_before = timezone.now() - datetime.timedelta(days=stale_after_days())
    return {
        'expired': queryset.filter(allowed=FlowAllowedChoices.YES, expires__lt=today).count(),
        'review_due': queryset.filter(review_by__lte=today).count(),
        'stale': queryset.filter(last_seen__lt=stale_before).count(),
        'no_conduit': queryset.filter(conduit__isnull=True).count(),
        'stale_after_days': stale_after_days(),
    }


#
# SVG diagram: one row per Purdue level (5 at the top, 0 at the bottom), zones as boxes, one arrow per directed
# zone pair coloured by its worst verdict.
#

LINE_COLORS = {'no': '#d63939', 'expired': '#d63939', 'unknown': '#f59f00', 'yes': '#2fb344'}
WORST = ('no', 'expired', 'unknown', 'yes')
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


def _verdict(flow):
    return 'expired' if flow.is_expired else flow.allowed


def access_map_svg(flows, zones=()):
    """Return an inline SVG (safe string) for the given flows; `zones` adds zones without flows."""
    flows = list(flows)
    all_zones = {z.pk: z for z in zones}
    for f in flows:
        all_zones.setdefault(f.source_zone_id, f.source_zone)
        all_zones.setdefault(f.destination_zone_id, f.destination_zone)
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
    # One arrow per directed zone pair
    pairs = {}
    for f in flows:
        pairs.setdefault((f.source_zone_id, f.destination_zone_id), []).append(f)
    pair_seen = {}
    for (src, dst), members in pairs.items():
        (sx, sy), (dx, dy) = pos[src], pos[dst]
        key = tuple(sorted((src, dst)))
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
        worst = min((_verdict(f) for f in members), key=WORST.index)
        color = LINE_COLORS.get(worst, '#888')
        dash = ' stroke-dasharray="6 4"' if any(f.remote_access for f in members) else ''
        title = escape('\n'.join(str(f) for f in members))
        lines.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"{dash} '
            f'marker-end="url(#iec-arrow)"><title>{title}</title></path>'
        )
        badges.append(
            f'<circle cx="{lx}" cy="{ly}" r="10" fill="{color}"/>'
            f'<text x="{lx}" y="{ly + 4}" text-anchor="middle" class="num">{len(members)}</text>'
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
