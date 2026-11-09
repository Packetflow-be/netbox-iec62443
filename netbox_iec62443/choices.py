from django.utils.translation import gettext_lazy as _

from utilities.choices import Choice, ChoiceSet


class PurdueLevelChoices(ChoiceSet):
    """Purdue reference model levels, as used by IEC 62443 and most OT asset tools."""
    LEVEL_0 = '0'
    LEVEL_1 = '1'
    LEVEL_2 = '2'
    LEVEL_3 = '3'
    LEVEL_3_5 = '3.5'
    LEVEL_4 = '4'
    LEVEL_5 = '5'

    CHOICES = (
        Choice(LEVEL_0, _('0 - Process (sensors, actuators)'), color='purple'),
        Choice(LEVEL_1, _('1 - Basic control (PLC, RTU)'), color='red'),
        Choice(LEVEL_2, _('2 - Supervisory (HMI, SCADA, engineering)'), color='orange'),
        Choice(LEVEL_3, _('3 - Site operations'), color='yellow'),
        Choice(LEVEL_3_5, _('3.5 - Industrial DMZ'), color='cyan'),
        Choice(LEVEL_4, _('4 - Business / office'), color='blue'),
        Choice(LEVEL_5, _('5 - Enterprise / internet'), color='gray'),
    )

    @classmethod
    def at_or_below(cls, level):
        """All level values numerically <= level (e.g. '2' -> ['0', '1', '2'])."""
        limit = float(level)
        return [value for value, _label in cls.CHOICES if float(value) <= limit]


class SecurityLevelChoices(ChoiceSet):
    """IEC 62443-3-3 security levels (used here as the zone's target, SL-T)."""
    SL_0 = 0
    SL_1 = 1
    SL_2 = 2
    SL_3 = 3
    SL_4 = 4

    CHOICES = (
        Choice(SL_0, _('SL 0 - No specific requirement')),
        Choice(SL_1, _('SL 1 - Casual or coincidental violation')),
        Choice(SL_2, _('SL 2 - Intentional, simple means')),
        Choice(SL_3, _('SL 3 - Intentional, sophisticated means')),
        Choice(SL_4, _('SL 4 - Intentional, sophisticated means, extended resources')),
    )


class ConduitDirectionChoices(ChoiceSet):
    ONE_WAY = 'one-way'
    TWO_WAY = 'two-way'

    CHOICES = (
        Choice(ONE_WAY, _('One-way'), color='gray'),
        Choice(TWO_WAY, _('Two-way'), color='blue'),
    )


class ConduitAllowedChoices(ChoiceSet):
    """Is this path allowed? The "Mag dat?" column of the access map."""
    YES = 'yes'
    NO = 'no'
    UNKNOWN = 'unknown'

    CHOICES = (
        Choice(YES, _('Yes'), color='green'),
        Choice(NO, _('No'), color='red'),
        Choice(UNKNOWN, _('Unknown'), color='yellow'),
    )
