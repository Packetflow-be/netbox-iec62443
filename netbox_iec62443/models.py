from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from netbox.models import PrimaryModel

from .choices import (
    ConduitAllowedChoices,
    ConduitDirectionChoices,
    FieldbusMediumChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
)

__all__ = ('Conduit', 'Fieldbus', 'IndustrialService', 'Zone')


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
    `allowed` is the access map's verdict: is this path allowed?
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
        help_text=_('Is this path allowed? Shown as the verdict on the access map'),
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

    @property
    def evidence_lines(self):
        """Evidence split into (first line, remaining lines) for compact display."""
        first, _sep, rest = self.evidence.strip().partition('\n')
        return first, rest

    def get_direction_color(self):
        return ConduitDirectionChoices.colors.get(self.direction)

    def get_allowed_color(self):
        return ConduitAllowedChoices.colors.get(self.allowed)


class Fieldbus(PrimaryModel):
    """
    A serial bus or fieldbus segment (RS-485, PROFIBUS, CAN, ...) that a passive network capture can't
    see. Its members are the industrial services on it; a gateway bridges it to Ethernet.
    """
    name = models.CharField(verbose_name=_('name'), max_length=100, db_collation='natural_sort')
    site = models.ForeignKey(
        to='dcim.Site',
        on_delete=models.PROTECT,
        related_name='iec62443_fieldbuses',
        blank=True,
        null=True,
    )
    zone = models.ForeignKey(
        to=Zone,
        on_delete=models.SET_NULL,
        related_name='fieldbuses',
        blank=True,
        null=True,
    )
    medium = models.CharField(
        verbose_name=_('medium'),
        max_length=20,
        choices=FieldbusMediumChoices,
    )
    protocol = models.CharField(
        verbose_name=_('protocol'),
        max_length=30,
        choices=IndustrialProtocolChoices,
        blank=True,
    )
    baud_rate = models.PositiveIntegerField(
        verbose_name=_('baud rate'),
        blank=True,
        null=True,
        help_text=_('Bits per second, e.g. 9600 or 19200'),
    )
    frame_format = models.CharField(
        verbose_name=_('frame format'),
        max_length=10,
        blank=True,
        help_text=_('Data bits, parity, stop bits, e.g. "8N1" or "8E1"'),
    )
    gateway = models.ForeignKey(
        to='dcim.Device',
        on_delete=models.SET_NULL,
        related_name='iec62443_gateway_for',
        verbose_name=_('gateway'),
        blank=True,
        null=True,
        help_text=_('Device that bridges this bus to Ethernet (serial device server, protocol gateway)'),
    )

    clone_fields = ('site', 'zone', 'medium', 'protocol', 'baud_rate', 'frame_format', 'gateway')

    class Meta:
        ordering = ('site', 'name')
        verbose_name = _('fieldbus')
        verbose_name_plural = _('fieldbuses')
        constraints = (
            models.UniqueConstraint(fields=('site', 'name'), name='%(app_label)s_%(class)s_unique_site_name',
                                    violation_error_message=_('Fieldbus name must be unique per site.')),
        )

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.zone_id and self.site_id and self.zone.site_id and self.zone.site_id != self.site_id:
            raise ValidationError({'zone': _('The zone belongs to another site.')})


class IndustrialService(PrimaryModel):
    """
    An industrial protocol spoken by a device or virtual machine: as server (slave, outstation) or client
    (master), over an interface and ports, or on a fieldbus at a station address.
    """
    device = models.ForeignKey(
        to='dcim.Device',
        on_delete=models.CASCADE,
        related_name='iec62443_services',
        blank=True,
        null=True,
    )
    virtual_machine = models.ForeignKey(
        to='virtualization.VirtualMachine',
        on_delete=models.CASCADE,
        related_name='iec62443_services',
        blank=True,
        null=True,
    )
    protocol = models.CharField(
        verbose_name=_('protocol'),
        max_length=30,
        choices=IndustrialProtocolChoices,
    )
    role = models.CharField(
        verbose_name=_('role'),
        max_length=20,
        choices=ServiceRoleChoices,
        default=ServiceRoleChoices.SERVER,
    )
    interface = models.ForeignKey(
        to='dcim.Interface',
        on_delete=models.SET_NULL,
        related_name='iec62443_services',
        verbose_name=_('interface'),
        blank=True,
        null=True,
    )
    ports = ArrayField(
        base_field=models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(65535)]),
        verbose_name=_('ports'),
        blank=True,
        default=list,
        help_text=_('TCP/UDP ports; left empty, the protocol\'s usual ports are filled in'),
    )
    fieldbus = models.ForeignKey(
        to=Fieldbus,
        on_delete=models.SET_NULL,
        related_name='services',
        verbose_name=_('fieldbus'),
        blank=True,
        null=True,
    )
    address = models.CharField(
        verbose_name=_('address'),
        max_length=50,
        blank=True,
        help_text=_('Unit ID, station or slave address, or rack/slot, e.g. "unit 1", "rack 0 slot 1"'),
    )
    evidence = models.TextField(
        verbose_name=_('evidence'),
        blank=True,
        help_text=_('Where this was seen (capture, configuration, site visit)'),
    )

    clone_fields = ('device', 'virtual_machine', 'protocol', 'role', 'fieldbus')

    class Meta:
        ordering = ('device', 'virtual_machine', 'protocol', 'role', 'pk')
        verbose_name = _('industrial service')
        verbose_name_plural = _('industrial services')

    def __str__(self):
        return f'{self.parent} {self.get_protocol_display()} ({self.get_role_display().split(" /")[0].lower()})'

    @property
    def parent(self):
        return self.device or self.virtual_machine

    @property
    def ports_display(self):
        return ', '.join(str(p) for p in self.ports)

    @property
    def is_serial(self):
        return self.protocol in IndustrialProtocolChoices.SERIAL

    def clean(self):
        super().clean()
        if bool(self.device_id) == bool(self.virtual_machine_id):
            raise ValidationError(_('An industrial service belongs to either a device or a virtual machine.'))
        if self.interface_id and self.interface.device_id != self.device_id:
            raise ValidationError({'interface': _('The interface belongs to another device.')})
        if self.is_serial:
            if self.ports:
                raise ValidationError({'ports': _('A serial protocol has no TCP/UDP ports.')})
        elif self.fieldbus_id and self.protocol != IndustrialProtocolChoices.OTHER:
            raise ValidationError({'fieldbus': _('Only serial or fieldbus protocols sit on a fieldbus.')})

    def save(self, *args, **kwargs):
        if not self.ports and not self.is_serial:
            self.ports = list(IndustrialProtocolChoices.DEFAULT_PORTS.get(self.protocol, []))
        super().save(*args, **kwargs)

    def get_role_color(self):
        return ServiceRoleChoices.colors.get(self.role)
