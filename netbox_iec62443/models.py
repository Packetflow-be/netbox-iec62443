from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from netbox.models import PrimaryModel

from .choices import ConduitAllowedChoices, ConduitDirectionChoices, PurdueLevelChoices, SecurityLevelChoices

__all__ = ('Conduit', 'Zone')


class Zone(PrimaryModel):
    """
    An IEC 62443 zone: a group of assets with the same security requirements.
    Members are devices, virtual machines and/or prefixes (plain many-to-many relations).
    """
    name = models.CharField(verbose_name=_('name'), max_length=100, db_collation='natural_sort')
    slug = models.SlugField(verbose_name=_('slug'), max_length=100)
    site = models.ForeignKey(
        to='dcim.Site',
        on_delete=models.PROTECT,
        related_name='iec62443_zones',
        blank=True,
        null=True,
    )
    tenant = models.ForeignKey(
        to='tenancy.Tenant',
        on_delete=models.PROTECT,
        related_name='iec62443_zones',
        blank=True,
        null=True,
    )
    purdue_level = models.CharField(
        verbose_name=_('Purdue level'),
        max_length=10,
        choices=PurdueLevelChoices,
        blank=True,
    )
    security_level_target = models.PositiveSmallIntegerField(
        verbose_name=_('security level target (SL-T)'),
        choices=SecurityLevelChoices,
        blank=True,
        null=True,
    )
    devices = models.ManyToManyField(
        to='dcim.Device',
        related_name='iec62443_zones',
        blank=True,
    )
    virtual_machines = models.ManyToManyField(
        to='virtualization.VirtualMachine',
        related_name='iec62443_zones',
        blank=True,
    )
    prefixes = models.ManyToManyField(
        to='ipam.Prefix',
        related_name='iec62443_zones',
        blank=True,
    )

    clone_fields = ('site', 'tenant', 'purdue_level', 'security_level_target')

    class Meta:
        ordering = ('site', 'name')
        verbose_name = _('zone')
        verbose_name_plural = _('zones')
        constraints = (
            models.UniqueConstraint(fields=('site', 'name'), name='%(app_label)s_%(class)s_unique_site_name',
                                    violation_error_message=_('Zone name must be unique per site.')),
            models.UniqueConstraint(fields=('name',), condition=Q(site__isnull=True),
                                    name='%(app_label)s_%(class)s_unique_name',
                                    violation_error_message=_('Zone name must be unique (no site).')),
            models.UniqueConstraint(fields=('site', 'slug'), name='%(app_label)s_%(class)s_unique_site_slug',
                                    violation_error_message=_('Zone slug must be unique per site.')),
            models.UniqueConstraint(fields=('slug',), condition=Q(site__isnull=True),
                                    name='%(app_label)s_%(class)s_unique_slug',
                                    violation_error_message=_('Zone slug must be unique (no site).')),
        )

    def __str__(self):
        return self.name

    def get_purdue_level_color(self):
        return PurdueLevelChoices.colors.get(self.purdue_level)

    @property
    def conduits(self):
        """All conduits that start or end in this zone."""
        return Conduit.objects.filter(Q(source_zone=self) | Q(destination_zone=self))


class Conduit(PrimaryModel):
    """
    An IEC 62443 conduit: a communication path between two zones.
    `allowed` is the access map's "Mag dat?" (is that allowed?) column.
    """
    name = models.CharField(verbose_name=_('name'), max_length=100, db_collation='natural_sort')
    source_zone = models.ForeignKey(
        to=Zone,
        on_delete=models.CASCADE,
        related_name='conduits_out',
        verbose_name=_('source zone'),
    )
    destination_zone = models.ForeignKey(
        to=Zone,
        on_delete=models.CASCADE,
        related_name='conduits_in',
        verbose_name=_('destination zone'),
    )
    direction = models.CharField(
        verbose_name=_('direction'),
        max_length=20,
        choices=ConduitDirectionChoices,
        default=ConduitDirectionChoices.ONE_WAY,
    )
    allowed = models.CharField(
        verbose_name=_('allowed'),
        max_length=20,
        choices=ConduitAllowedChoices,
        default=ConduitAllowedChoices.UNKNOWN,
        help_text=_('Is this path allowed? (the access map\'s "Mag dat?" column)'),
    )
    protocols = models.CharField(
        verbose_name=_('protocols / ports'),
        max_length=200,
        blank=True,
        help_text=_('Free text, e.g. "S7comm (TCP/102) read+write, Modbus/TCP 502"'),
    )
    remote_access = models.BooleanField(
        verbose_name=_('remote access'),
        default=False,
        help_text=_('Access from outside the site (supplier 4G router, VPN, TeamViewer, ...)'),
    )
    via = models.CharField(
        verbose_name=_('via'),
        max_length=200,
        blank=True,
        help_text=_('How the path runs, e.g. "4G router of supplier X", "firewall FW01"'),
    )
    evidence = models.TextField(
        verbose_name=_('evidence'),
        blank=True,
        help_text=_('Where this path was seen (capture, interview, configuration)'),
    )

    clone_fields = ('source_zone', 'destination_zone', 'direction', 'allowed', 'protocols', 'remote_access', 'via')

    class Meta:
        ordering = ('source_zone', 'destination_zone', 'name')
        verbose_name = _('conduit')
        verbose_name_plural = _('conduits')
        constraints = (
            models.UniqueConstraint(
                fields=('source_zone', 'destination_zone', 'name'),
                name='%(app_label)s_%(class)s_unique_zones_name',
                violation_error_message=_('A conduit with this name already exists between these zones.'),
            ),
        )

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.source_zone_id and self.source_zone_id == self.destination_zone_id:
            raise ValidationError({
                'destination_zone': _('A conduit connects two different zones.'),
            })

    def get_direction_color(self):
        return ConduitDirectionChoices.colors.get(self.direction)

    def get_allowed_color(self):
        return ConduitAllowedChoices.colors.get(self.allowed)
