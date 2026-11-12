"""
IEC 62443-3-3 system requirements: loading them, and which ones apply to a zone or conduit.

Copyright rule: the plugin ships identifiers and foundational requirements only (data/iec62443-3-3-2013.csv). The
requirement wording and the lowest security level at which each requirement or enhancement applies come from the
user's own licensed copy of the standard, through `load_csv()`, into the user's own database.

CSV columns (a header row is required; names are case-insensitive):
  identifier                  SR 1.1, or SR 1.1 RE 1 for a requirement enhancement (required)
  foundational_requirement    iac, uc, si, dc, rdf, tre, ra (or fr); optional, it follows from the identifier
  security_level              1-4, the lowest SL at which it applies (or sl); optional
  wording                     the requirement text; optional
An empty cell leaves the stored value alone. Lines starting with # are skipped.
"""
import csv
import io
import re
from collections import Counter
from pathlib import Path

from .choices import FoundationalRequirementChoices, RequirementEditionChoices, RequirementStatusChoices

SHIPPED = {
    RequirementEditionChoices.IEC_62443_3_3_2013: Path(__file__).parent / 'data' / 'iec62443-3-3-2013.csv',
}
ALIASES = {'fr': 'foundational_requirement', 'sl': 'security_level', 'text': 'wording'}


def normalise(identifier):
    """'sr1.1re1', 'SR 1.1 RE1' -> 'SR 1.1 RE 1'."""
    text = re.sub(r'\s*RE\s*', ' RE ', str(identifier).upper())
    text = re.sub(r'^\s*(SR|CR)\s*', r'\1 ', text)
    return ' '.join(text.split())


def read_rows(text):
    """Rows of a requirements CSV as dicts with normalised column names."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    reader = csv.DictReader(io.StringIO('\n'.join(lines)))
    if not reader.fieldnames or 'identifier' not in [f.strip().lower() for f in reader.fieldnames]:
        raise ValueError('The CSV needs a header row with at least an "identifier" column')
    rows = []
    for i, row in enumerate(reader, start=2):
        clean = {}
        for key, value in row.items():
            if key is None:
                raise ValueError(f'line {i}: more cells than columns')
            key = key.strip().lower()
            clean[ALIASES.get(key, key)] = (value or '').strip()
        rows.append(clean)
    return rows


def load_rows(rows, edition=RequirementEditionChoices.IEC_62443_3_3_2013, log=None):
    """
    Create or update requirements from `rows` (see read_rows). Requirements before their enhancements; an
    enhancement whose requirement is missing gets it created. Returns counts.
    """
    from .models import REQUIREMENT_IDENTIFIER, SystemRequirement

    stats = Counter()
    frs = FoundationalRequirementChoices.values()
    parsed = []
    for row in rows:
        identifier = normalise(row.get('identifier', ''))
        match = REQUIREMENT_IDENTIFIER.match(identifier)
        if not match:
            raise ValueError(f'{row.get("identifier")!r} is not a requirement identifier (SR 1.1, SR 1.1 RE 1)')
        fr = row.get('foundational_requirement', '').lower()
        if fr and fr not in frs:
            raise ValueError(f'{identifier}: foundational requirement {fr!r} is not one of {", ".join(frs)}')
        level = row.get('security_level', '')
        if level and level not in ('1', '2', '3', '4'):
            raise ValueError(f'{identifier}: security level {level!r} is not 1-4')
        parsed.append((identifier, match, fr, int(level) if level else None, row.get('wording', '')))

    existing = {r.identifier: r for r in SystemRequirement.objects.filter(edition=edition)}

    def ensure(identifier, match, fr, level=None, wording=''):
        obj = existing.get(identifier)
        created = obj is None
        if created:
            obj = SystemRequirement(edition=edition, identifier=identifier)
        else:
            obj.snapshot()
        before = (obj.foundational_requirement, obj.security_level, obj.wording, obj.parent_id)
        obj.foundational_requirement = fr or obj.foundational_requirement or frs[int(match.group(2)) - 1]
        if level is not None:
            obj.security_level = level
        if wording:
            obj.wording = wording
        if match.group(4):
            base = f'{match.group(1)} {match.group(2)}.{match.group(3)}'
            obj.parent = existing.get(base) or ensure(base, REQUIREMENT_IDENTIFIER.match(base), '')
        if created or before != (obj.foundational_requirement, obj.security_level, obj.wording, obj.parent_id):
            obj.full_clean()
            obj.save()
            existing[identifier] = obj
            stats['created' if created else 'updated'] += 1
            if log:
                log(f"{'created' if created else 'updated'}: {identifier}")
        else:
            stats['unchanged'] += 1
        return obj

    # Requirements first, so enhancements find their parent
    for identifier, match, fr, level, wording in sorted(parsed, key=lambda p: bool(p[1].group(4))):
        ensure(identifier, match, fr, level, wording)
    return dict(stats)


def load_shipped(edition=RequirementEditionChoices.IEC_62443_3_3_2013, log=None):
    """Create the identifiers the plugin ships for `edition` (never touches levels or wording)."""
    return load_rows(read_rows(SHIPPED[edition].read_text(encoding='utf-8')), edition, log)


def applicable(requirements, levels):
    """The requirements (and enhancements) that apply at the security level vector `levels`."""
    return [r for r in requirements if r.applies_at(levels)]


def open_requirements(subject, requirements, statuses):
    """
    For a zone or conduit: (applicable requirements without a status, not-met requirements its SL-A claims).
    `statuses` maps requirement id -> RequirementStatus of this subject.
    """
    missing = [r for r in applicable(requirements, subject.sl_target) if r.pk not in statuses]
    claimed = [
        r for r in applicable(requirements, subject.sl_achieved)
        if r.pk in statuses and statuses[r.pk].status == RequirementStatusChoices.NOT_MET
    ]
    return missing, claimed
