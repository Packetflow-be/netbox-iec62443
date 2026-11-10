"""
Security level vectors: one level (0-4) per foundational requirement, in FR order
(IAC, UC, SI, DC, RDF, TRE, RA), e.g. SL-T {2 2 2 1 2 1 1}. Stored as a 7-element integer array, or NULL
when not set. A single number means the same level for every FR.
"""
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from .choices import FoundationalRequirementChoices

FR_COUNT = 7
FR_SHORT = ('IAC', 'UC', 'SI', 'DC', 'RDF', 'TRE', 'RA')


def parse(value):
    """'2' -> [2]*7; '2,2,2,1,2,1,1' or '2 2 2 1 2 1 1' or '{2 2 2 1 2 1 1}' -> list; '' -> None."""
    if value in (None, '', []):
        return None
    if isinstance(value, (list, tuple)):
        levels = list(value)
    else:
        text = str(value).strip().strip('{}[]()').replace(',', ' ').split()
        try:
            levels = [int(x) for x in text]
        except ValueError:
            raise ValidationError(_('A security level vector is one level (0-4) or seven, one per FR.'))
    if len(levels) == 1:
        levels = levels * FR_COUNT
    validate(levels)
    return levels


def validate(levels):
    if levels is None:
        return
    if len(levels) != FR_COUNT or any(not isinstance(x, int) or not 0 <= x <= 4 for x in levels):
        raise ValidationError(_('A security level vector has seven levels from 0 to 4, one per FR (IAC, UC, SI, DC, '
                                'RDF, TRE, RA).'))


def display(levels):
    """'{2 2 2 1 2 1 1}', or '' when not set."""
    return '{' + ' '.join(str(x) for x in levels) + '}' if levels else ''


def short(levels):
    """'2' when all FRs are equal, else the vector."""
    if not levels:
        return ''
    return str(levels[0]) if len(set(levels)) == 1 else display(levels)


def below(levels, reference):
    """FR labels where `levels` is below `reference` (both set), e.g. ['IAC', 'RDF']."""
    if not levels or not reference:
        return []
    return [FR_SHORT[i] for i in range(FR_COUNT) if levels[i] < reference[i]]


def minimum(vectors):
    """Per-FR minimum of the vectors that are set, or None."""
    vectors = [v for v in vectors if v]
    return [min(v[i] for v in vectors) for i in range(FR_COUNT)] if vectors else None


def maximum(vectors):
    vectors = [v for v in vectors if v]
    return [max(v[i] for v in vectors) for i in range(FR_COUNT)] if vectors else None


def gap_q(achieved, target):
    """Q for rows where `achieved` is below `target` in any FR (both set)."""
    q = Q()
    for i in range(FR_COUNT):
        q |= Q(**{f'{achieved}__{i}__lt': F(f'{target}__{i}')})
    return Q(**{f'{achieved}__isnull': False, f'{target}__isnull': False}) & q


def rows(target, achieved=None):
    """[(FR label, target, achieved, gap?)] for a panel."""
    labels = [str(label) for _value, label in FoundationalRequirementChoices.CHOICES]
    return [
        (labels[i], target[i] if target else None, achieved[i] if achieved else None,
         bool(target and achieved and achieved[i] < target[i]))
        for i in range(FR_COUNT)
    ]
