import datetime

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from netbox.models import PrimaryModel

from .choices import (
    AccessChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    SecurityLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)

__all__ = ('Conduit', 'Fieldbus', 'Flow', 'FlowHop', 'IndustrialService', 'Zone')


def stale_after_days():
    return int(settings.PLUGINS_CONFIG.get('netbox_iec62443', {}).get('stale_after_days', 90))


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
    zone_type = models.CharField(
        verbose_name=_('zone type'),
        max_length=20,
        choices=ZoneTypeChoices,
        default=ZoneTypeChoices.OT,
        help_text=_('An MSP or supplier is an external zone'),
    )
    purdue_level = models.CharField(
        verbose_name=_('Purdue level'),
        max_length=10,
        choices=PurdueLevelChoices,
        blank=True,
        help_text=_('The most critical (lowest) level in the zone; the access map counts the zone by it'),
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

    clone_fields = ('site', 'tenant', 'zone_type', 'purdue_level', 'security_level_target')

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

    def get_zone_type_color(self):
        return ZoneTypeChoices.colors.get(self.zone_type)

    @property
    def flows(self):
        """All flows that start or end in this zone."""
        return Flow.objects.filter(Q(source_zone=self) | Q(destination_zone=self))


class Conduit(PrimaryModel):
    """
    An IEC 62443-3-2 conduit: the communication channels between two or more zones, grouped because they share
    security requirements. It has its own SL-T and names the devices that enforce it (firewalls, data diodes,
    gateways). What actually runs through it is recorded as flows.
    """
    name = models.CharField(verbose_name=_('name'), max_length=100, db_collation='natural_sort')
    site = models.ForeignKey(
        to='dcim.Site',
        on_delete=models.PROTECT,
        related_name='iec62443_conduits',
        blank=True,
        null=True,
    )
    zones = models.ManyToManyField(
        to=Zone,
        related_name='conduits',
        verbose_name=_('zones'),
        help_text=_('The zones this conduit joins (two or more)'),
    )
    security_level_target = models.PositiveSmallIntegerField(
        verbose_name=_('security level target (SL-T)'),
        choices=SecurityLevelChoices,
        blank=True,
        null=True,
    )
    enforcing_devices = models.ManyToManyField(
        to='dcim.Device',
        related_name='iec62443_enforced_conduits',
        verbose_name=_('enforcing devices'),
        blank=True,
        help_text=_('Firewalls, data diodes, gateways that enforce this conduit'),
    )
    enforcing_virtual_machines = models.ManyToManyField(
        to='virtualization.VirtualMachine',
        related_name='iec62443_enforced_conduits',
        verbose_name=_('enforcing virtual machines'),
        blank=True,
    )

    clone_fields = ('site', 'security_level_target')

    class Meta:
        ordering = ('site', 'name')
        verbose_name = _('conduit')
        verbose_name_plural = _('conduits')
        constraints = (
            models.UniqueConstraint(fields=('site', 'name'), name='%(app_label)s_%(class)s_unique_site_name',
                                    violation_error_message=_('Conduit name must be unique per site.')),
            models.UniqueConstraint(fields=('name',), condition=Q(site__isnull=True),
                                    name='%(app_label)s_%(class)s_unique_name',
                                    violation_error_message=_('Conduit name must be unique (no site).')),
        )

    def __str__(self):
        return self.name


class Flow(PrimaryModel):
    """
    A directed communication path from one zone into another: protocol and ports, what the requests do, the ordered
    hops it runs through, and the verdict (is it allowed?) with who decided it and until when. Tools supply the
    evidence and the first/last seen times; a person decides. A flow belongs to the conduit that carries it.
    """
    name = models.CharField(
        verbose_name=_('name'),
        max_length=100,
        db_collation='natural_sort',
        blank=True,
        help_text=_('Left empty, it is made from the zones and the protocol'),
    )
    conduit = models.ForeignKey(
        to=Conduit,
        on_delete=models.SET_NULL,
        related_name='flows',
        verbose_name=_('conduit'),
        blank=True,
        null=True,
        help_text=_('The conduit that carries this flow; empty means no documented conduit'),
    )
    source_zone = models.ForeignKey(
        to=Zone,
        on_delete=models.PROTECT,
        related_name='flows_out',
        verbose_name=_('source zone'),
    )
    destination_zone = models.ForeignKey(
        to=Zone,
        on_delete=models.PROTECT,
        related_name='flows_in',
        verbose_name=_('destination zone'),
    )
    protocol = models.CharField(
        verbose_name=_('protocol'),
        max_length=30,
        choices=FlowProtocolChoices,
        blank=True,
    )
    port_mappings = ArrayField(
        base_field=models.CharField(max_length=63),
        verbose_name=_('ports'),
        blank=True,
        default=list,
        help_text=_('Destination ports as protocol/port, e.g. tcp/102; empty for layer-2 protocols'),
    )
    access = ArrayField(
        base_field=models.CharField(max_length=20, choices=AccessChoices),
        verbose_name=_('access'),
        blank=True,
        default=list,
        help_text=_('What the requests do to the destination: read, write, control, program'),
    )
    remote_access = models.BooleanField(
        verbose_name=_('remote access'),
        default=False,
        help_text=_('Access from outside the site (supplier 4G router, VPN, TeamViewer, MSP, ...)'),
    )
    allowed = models.CharField(
        verbose_name=_('allowed'),
        max_length=20,
        choices=FlowAllowedChoices,
        default=FlowAllowedChoices.UNKNOWN,
        help_text=_('Is this flow allowed? Shown as the verdict on the access map'),
    )
    decided_by = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='iec62443_flow_verdicts',
        verbose_name=_('decided by'),
        blank=True,
        null=True,
    )
    decided_on = models.DateField(
        verbose_name=_('decided on'),
        blank=True,
        null=True,
        help_text=_('Filled in with today when the verdict changes and no date is given'),
    )
    review_by = models.DateField(
        verbose_name=_('review by'),
        blank=True,
        null=True,
        help_text=_('Date by which the verdict should be reviewed'),
    )
    expires = models.DateField(
        verbose_name=_('expires'),
        blank=True,
        null=True,
        help_text=_('An allowed flow is no longer allowed after this date (e.g. temporary supplier access)'),
    )
    first_seen = models.DateTimeField(verbose_name=_('first seen'), blank=True, null=True)
    last_seen = models.DateTimeField(verbose_name=_('last seen'), blank=True, null=True)
    evidence = models.TextField(
        verbose_name=_('evidence'),
        blank=True,
        help_text=_('Where this flow was seen (capture, interview, configuration)'),
    )

    clone_fields = (
        'conduit', 'source_zone', 'destination_zone', 'protocol', 'port_mappings', 'access', 'remote_access',
    )

    class Meta:
        ordering = ('source_zone', 'destination_zone', 'name')
        verbose_name = _('flow')
        verbose_name_plural = _('flows')
        constraints = (
            models.UniqueConstraint(
                fields=('source_zone', 'destination_zone', 'name'),
                name='%(app_label)s_%(class)s_unique_zones_name',
                violation_error_message=_('A flow with this name already exists between these zones.'),
            ),
        )

    def __str__(self):
        return self.name or self.default_name()

    def default_name(self):
        parts = [f'{self.source_zone} -> {self.destination_zone}'] if self.source_zone_id and \
            self.destination_zone_id else []
        if self.protocol:
            parts.append(str(self.get_protocol_display()))
        return ' '.join(parts)[:100]

    def clean(self):
        super().clean()
        from ipam.validators import validate_port_mappings

        if self.source_zone_id and self.source_zone_id == self.destination_zone_id:
            raise ValidationError({'destination_zone': _('A flow runs between two different zones.')})
        try:
            self.port_mappings = validate_port_mappings(self.port_mappings or [])
        except ValidationError as e:
            raise ValidationError({'port_mappings': e.messages})
        if self.conduit_id and self.source_zone_id and self.destination_zone_id:
            joined = set(self.conduit.zones.values_list('pk', flat=True))
            if not {self.source_zone_id, self.destination_zone_id} <= joined:
                raise ValidationError({'conduit': _('The conduit does not join both zones of this flow.')})
        if self.first_seen and self.last_seen and self.first_seen > self.last_seen:
            raise ValidationError({'last_seen': _('Last seen is before first seen.')})

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.default_name()
        self.access = sorted(set(self.access or []), key=AccessChoices.values().index)
        # Who decided and when go with the verdict: an unknown verdict has neither, and a verdict that changes
        # without a new date given is dated today.
        if self.allowed == FlowAllowedChoices.UNKNOWN:
            self.decided_on = None
            self.decided_by = None
        else:
            before = Flow.objects.filter(pk=self.pk).values('allowed', 'decided_on').first() if self.pk else None
            if before is None:
                self.decided_on = self.decided_on or timezone.localdate()
            elif before['allowed'] != self.allowed and before['decided_on'] == self.decided_on:
                self.decided_on = timezone.localdate()
        super().save(*args, **kwargs)

    @property
    def evidence_lines(self):
        """Evidence split into (first line, remaining lines) for compact display."""
        first, _sep, rest = self.evidence.strip().partition('\n')
        return first, rest

    @property
    def ports_display(self):
        return ', '.join(m.upper() for m in self.port_mappings)

    @property
    def is_modifying(self):
        return any(a in AccessChoices.MODIFYING for a in self.access)

    @property
    def is_expired(self):
        return self.allowed == FlowAllowedChoices.YES and bool(self.expires) and self.expires < timezone.localdate()

    @property
    def is_review_due(self):
        return bool(self.review_by) and self.review_by <= timezone.localdate()

    @property
    def is_stale(self):
        """Not seen for `stale_after_days` (plugin setting, default 90). Flows never observed are not stale."""
        return bool(self.last_seen) and self.last_seen < timezone.now() - datetime.timedelta(days=stale_after_days())

    def get_allowed_color(self):
        return FlowAllowedChoices.colors.get(self.allowed)

    def get_access_display(self):
        labels = dict(AccessChoices.CHOICES)
        return [(a, labels.get(a, a), AccessChoices.colors.get(a)) for a in self.access]


class FlowHop(PrimaryModel):
    """One step on a flow's path, in order: a device (firewall, jump host, gateway), a VM or a tunnel."""
    flow = models.ForeignKey(
        to=Flow,
        on_delete=models.CASCADE,
        related_name='hops',
        verbose_name=_('flow'),
    )
    position = models.PositiveSmallIntegerField(
        verbose_name=_('position'),
        help_text=_('Order along the path, from the source (1) to the destination'),
    )
    device = models.ForeignKey(
        to='dcim.Device',
        on_delete=models.CASCADE,
        related_name='iec62443_flow_hops',
        blank=True,
        null=True,
    )
    virtual_machine = models.ForeignKey(
        to='virtualization.VirtualMachine',
        on_delete=models.CASCADE,
        related_name='iec62443_flow_hops',
        blank=True,
        null=True,
    )
    tunnel = models.ForeignKey(
        to='vpn.Tunnel',
        on_delete=models.CASCADE,
        related_name='iec62443_flow_hops',
        blank=True,
        null=True,
    )

    clone_fields = ('flow',)

    class Meta:
        ordering = ('flow', 'position')
        verbose_name = _('flow hop')
        verbose_name_plural = _('flow hops')
        constraints = (
            models.UniqueConstraint(fields=('flow', 'position'), name='%(app_label)s_%(class)s_unique_flow_position',
                                    violation_error_message=_('This flow already has a hop at this position.')),
        )

    def __str__(self):
        return f'{self.position}. {self.hop}'

    @property
    def hop(self):
        return self.device or self.virtual_machine or self.tunnel

    def clean(self):
        super().clean()
        if sum(bool(x) for x in (self.device_id, self.virtual_machine_id, self.tunnel_id)) != 1:
            raise ValidationError(_('A hop is exactly one device, virtual machine or tunnel.'))


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
    gateway = models.ForeignKey(
        to='dcim.Device',
        on_delete=models.SET_NULL,
        related_name='iec62443_gateway_for',
        verbose_name=_('gateway'),
        blank=True,
        null=True,
        help_text=_('Device that bridges this bus to Ethernet (serial device server, protocol gateway)'),
    )

    clone_fields = ('site', 'zone', 'medium', 'protocol', 'gateway')

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
    (master). Over the network its ports are those of a NetBox application service; on a serial bus it sits on a
    fieldbus at a station address.
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
    service = models.ForeignKey(
        to='ipam.Service',
        on_delete=models.SET_NULL,
        related_name='iec62443_industrial_services',
        verbose_name=_('application service'),
        blank=True,
        null=True,
        help_text=_('The NetBox application service that holds the ports and IP addresses'),
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
        return self.service.port_mappings_list if self.service_id else ''

    @property
    def is_serial(self):
        return self.protocol in IndustrialProtocolChoices.SERIAL

    def clean(self):
        super().clean()
        if bool(self.device_id) == bool(self.virtual_machine_id):
            raise ValidationError(_('An industrial service belongs to either a device or a virtual machine.'))
        if self.service_id:
            if self.is_serial:
                raise ValidationError({'service': _('A serial protocol has no application service (no ports).')})
            if self.service.parent != self.parent:
                raise ValidationError({'service': _('The application service belongs to another device or VM.')})
        if not self.is_serial and self.fieldbus_id and self.protocol != IndustrialProtocolChoices.OTHER:
            raise ValidationError({'fieldbus': _('Only serial or fieldbus protocols sit on a fieldbus.')})

    def get_role_color(self):
        return ServiceRoleChoices.colors.get(self.role)
