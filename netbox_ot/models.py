import datetime
import re

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from netbox.models import PrimaryModel

from . import risk, sl
from .choices import (
    AccessChoices,
    ConnectionChoices,
    FieldbusMediumChoices,
    FlowAllowedChoices,
    FlowProtocolChoices,
    FoundationalRequirementChoices,
    IndustrialProtocolChoices,
    PurdueLevelChoices,
    RequirementEditionChoices,
    RequirementStatusChoices,
    RiskAssessmentKindChoices,
    RiskAssessmentStatusChoices,
    RiskLevelChoices,
    ServiceRoleChoices,
    ZoneTypeChoices,
)

__all__ = (
    'Conduit', 'Fieldbus', 'Flow', 'FlowHop', 'IndustrialService', 'PluginSettings', 'RequirementStatus',
    'RiskAssessment', 'SystemRequirement', 'Zone',
)


def stale_after_days():
    return int(settings.PLUGINS_CONFIG.get('netbox_ot', {}).get('stale_after_days', 90))


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
        related_name='ot_zones',
        blank=True,
        null=True,
    )
    tenant = models.ForeignKey(
        to='tenancy.Tenant',
        on_delete=models.PROTECT,
        related_name='ot_zones',
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
    sl_target = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        size=7,
        verbose_name=_('SL-T'),
        blank=True,
        null=True,
        validators=[sl.validate],
        help_text=_('Security level target per FR (IAC, UC, SI, DC, RDF, TRE, RA), 0-4'),
    )
    sl_achieved = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        size=7,
        verbose_name=_('SL-A'),
        blank=True,
        null=True,
        validators=[sl.validate],
        help_text=_('Security level achieved per FR, as assessed'),
    )
    accountable = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='%(app_label)s_%(class)s_accountable_for',
        verbose_name=_('accountable'),
        blank=True,
        null=True,
        help_text=_('The person accountable for its security'),
    )
    parent = models.ForeignKey(
        to='self',
        on_delete=models.SET_NULL,
        related_name='subzones',
        verbose_name=_('parent zone'),
        blank=True,
        null=True,
        help_text=_('Makes this a sub-zone of another zone'),
    )
    wireless = models.BooleanField(
        verbose_name=_('wireless'),
        default=False,
        help_text=_('The zone has wireless devices or links (IEC 62443-3-2 asks for them to be identified)'),
    )
    temporary_devices = models.BooleanField(
        verbose_name=_('temporarily connected devices'),
        default=False,
        help_text=_('Laptops, USB media or service devices are connected to the zone from time to time'),
    )
    devices = models.ManyToManyField(
        to='dcim.Device',
        related_name='ot_zones',
        blank=True,
    )
    virtual_machines = models.ManyToManyField(
        to='virtualization.VirtualMachine',
        related_name='ot_zones',
        blank=True,
    )
    prefixes = models.ManyToManyField(
        to='ipam.Prefix',
        related_name='ot_zones',
        blank=True,
    )

    clone_fields = ('site', 'tenant', 'zone_type', 'purdue_level', 'sl_target', 'parent', 'accountable')

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

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({'parent': _('A zone cannot be its own parent.')})
            ancestor, seen = self.parent, set()
            while ancestor is not None and ancestor.pk not in seen:
                if ancestor.pk == self.pk:
                    raise ValidationError({'parent': _('This would make the zone a sub-zone of itself.')})
                seen.add(ancestor.pk)
                ancestor = ancestor.parent
            if self.site_id and self.parent.site_id and self.parent.site_id != self.site_id:
                raise ValidationError({'parent': _('The parent zone belongs to another site.')})

    @property
    def sl_target_display(self):
        return sl.display(self.sl_target)

    @property
    def sl_achieved_display(self):
        return sl.display(self.sl_achieved)

    @property
    def sl_gap(self):
        return sl.below(self.sl_achieved, self.sl_target)

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
        related_name='ot_conduits',
        blank=True,
        null=True,
    )
    zones = models.ManyToManyField(
        to=Zone,
        related_name='conduits',
        verbose_name=_('zones'),
        help_text=_('The zones this conduit joins (two or more)'),
    )
    sl_target = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        size=7,
        verbose_name=_('SL-T'),
        blank=True,
        null=True,
        validators=[sl.validate],
        help_text=_('Security level target per FR (IAC, UC, SI, DC, RDF, TRE, RA), 0-4'),
    )
    sl_achieved = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        size=7,
        verbose_name=_('SL-A'),
        blank=True,
        null=True,
        validators=[sl.validate],
        help_text=_('Security level achieved per FR, as assessed'),
    )
    accountable = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='%(app_label)s_%(class)s_accountable_for',
        verbose_name=_('accountable'),
        blank=True,
        null=True,
        help_text=_('The person accountable for its security'),
    )
    enforcing_devices = models.ManyToManyField(
        to='dcim.Device',
        related_name='ot_enforced_conduits',
        verbose_name=_('enforcing devices'),
        blank=True,
        help_text=_('Firewalls, data diodes, gateways that enforce this conduit'),
    )
    enforcing_virtual_machines = models.ManyToManyField(
        to='virtualization.VirtualMachine',
        related_name='ot_enforced_conduits',
        verbose_name=_('enforcing virtual machines'),
        blank=True,
    )

    clone_fields = ('site', 'sl_target', 'accountable')

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

    @property
    def sl_target_display(self):
        return sl.display(self.sl_target)

    @property
    def sl_achieved_display(self):
        return sl.display(self.sl_achieved)

    @property
    def sl_gap(self):
        return sl.below(self.sl_achieved, self.sl_target)


class Flow(PrimaryModel):
    """
    A directed communication path from one zone into another: protocol and ports, what the requests do, the ordered
    hops it runs through, and the verdict (is it allowed?) with who decided it and until when. Tools supply the
    evidence and the first/last seen times; a person decides. A flow belongs to the conduit that carries it.

    The source is the side whose requests or data act on the destination. Usually it also opens the connection;
    `connection` says when it does not (reverse connect) or when a broker sits in between (`broker_zone`).
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
    connection = models.CharField(
        verbose_name=_('connection'),
        max_length=20,
        choices=ConnectionChoices,
        default=ConnectionChoices.CLIENT_SERVER,
        help_text=_('Who opens the connection, and whether a broker sits in between'),
    )
    broker_zone = models.ForeignKey(
        to=Zone,
        on_delete=models.PROTECT,
        related_name='flows_brokered',
        verbose_name=_('broker zone'),
        blank=True,
        null=True,
        help_text=_('The zone of the broker both ends connect to (only for a flow through a broker)'),
    )
    topics = ArrayField(
        base_field=models.CharField(max_length=255),
        verbose_name=_('topics'),
        blank=True,
        default=list,
        help_text=_('MQTT topics or OPC UA PubSub data sets this flow carries, e.g. spBv1.0/line1/DCMD/#'),
    )
    port_mappings = ArrayField(
        base_field=models.CharField(max_length=63),
        verbose_name=_('ports'),
        blank=True,
        default=list,
        help_text=_('Ports of the side that accepts the connection, as protocol/port, e.g. tcp/102: the '
                    'destination, the source for reverse connect, the broker for a brokered flow; empty for '
                    'layer-2 protocols'),
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
        related_name='ot_flow_verdicts',
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
        'conduit', 'source_zone', 'destination_zone', 'protocol', 'connection', 'broker_zone', 'port_mappings',
        'access', 'remote_access',
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
        if self.connection == ConnectionChoices.BROKERED and not self.broker_zone_id:
            raise ValidationError({'broker_zone': _('A flow through a broker names the zone of the broker.')})
        if self.connection != ConnectionChoices.BROKERED and self.broker_zone_id:
            raise ValidationError({'broker_zone': _('Only a flow through a broker has a broker zone.')})
        if self.conduit_id and self.source_zone_id and self.destination_zone_id:
            joined = set(self.conduit.zones.values_list('pk', flat=True))
            if not {self.source_zone_id, self.destination_zone_id} <= joined:
                raise ValidationError({'conduit': _('The conduit does not join both zones of this flow.')})
            if self.broker_zone_id and self.broker_zone_id not in joined:
                raise ValidationError({'conduit': _('The conduit does not join the broker zone of this flow.')})
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

    def get_connection_color(self):
        return ConnectionChoices.colors.get(self.connection)

    @property
    def is_outbound_only(self):
        """The destination's zone takes no inbound connection for this flow (reverse connect, brokered)."""
        return self.connection in ConnectionChoices.OUTBOUND_ONLY

    @property
    def connection_description(self):
        return ConnectionChoices.DESCRIPTIONS.get(self.connection, '')

    @property
    def transport_legs(self):
        """
        The connections a firewall sees for this flow, as (initiating zone, accepting zone) pairs: the source to
        the destination; the destination to the source for reverse connect; both ends to the broker zone.
        """
        if self.connection == ConnectionChoices.REVERSE_CONNECT:
            return [(self.destination_zone, self.source_zone)]
        if self.connection == ConnectionChoices.BROKERED and self.broker_zone_id:
            legs = []
            for zone in (self.source_zone, self.destination_zone):
                if zone.pk != self.broker_zone_id:
                    legs.append((zone, self.broker_zone))
            return legs
        return [(self.source_zone, self.destination_zone)]

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
        related_name='ot_flow_hops',
        blank=True,
        null=True,
    )
    virtual_machine = models.ForeignKey(
        to='virtualization.VirtualMachine',
        on_delete=models.CASCADE,
        related_name='ot_flow_hops',
        blank=True,
        null=True,
    )
    tunnel = models.ForeignKey(
        to='vpn.Tunnel',
        on_delete=models.CASCADE,
        related_name='ot_flow_hops',
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
        related_name='ot_fieldbuses',
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
        related_name='ot_gateway_for',
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
        related_name='ot_services',
        blank=True,
        null=True,
    )
    virtual_machine = models.ForeignKey(
        to='virtualization.VirtualMachine',
        on_delete=models.CASCADE,
        related_name='ot_services',
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
        related_name='ot_industrial_services',
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


class RiskAssessment(PrimaryModel):
    """
    An IEC 62443-3-2 risk assessment of a zone or a conduit: the initial (worst case, ZCR 2) or the detailed one
    (ZCR 5), with the unmitigated and residual risk against the organisation's tolerable risk. Keep every
    assessment; the latest approved one is the one that counts.
    """
    zone = models.ForeignKey(
        to=Zone,
        on_delete=models.PROTECT,
        related_name='risk_assessments',
        blank=True,
        null=True,
    )
    conduit = models.ForeignKey(
        to=Conduit,
        on_delete=models.PROTECT,
        related_name='risk_assessments',
        blank=True,
        null=True,
    )
    kind = models.CharField(
        verbose_name=_('kind'),
        max_length=20,
        choices=RiskAssessmentKindChoices,
        default=RiskAssessmentKindChoices.DETAILED,
    )
    status = models.CharField(
        verbose_name=_('status'),
        max_length=20,
        choices=RiskAssessmentStatusChoices,
        default=RiskAssessmentStatusChoices.DRAFT,
    )
    assessed_on = models.DateField(verbose_name=_('assessed on'))
    assessed_by = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='ot_risk_assessments',
        verbose_name=_('assessed by'),
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='ot_risk_assessments_approved',
        verbose_name=_('approved by'),
        blank=True,
        null=True,
    )
    approved_on = models.DateField(verbose_name=_('approved on'), blank=True, null=True)
    next_review = models.DateField(verbose_name=_('next review'), blank=True, null=True)
    method = models.CharField(
        verbose_name=_('method'),
        max_length=200,
        blank=True,
        help_text=_('The risk matrix or method used, e.g. the company risk matrix'),
    )
    threats = models.TextField(verbose_name=_('threats'), blank=True)
    vulnerabilities = models.TextField(verbose_name=_('vulnerabilities'), blank=True)
    consequences = models.TextField(verbose_name=_('consequences'), blank=True)
    unmitigated_risk = models.CharField(
        verbose_name=_('unmitigated risk'),
        max_length=20,
        choices=RiskLevelChoices,
        blank=True,
    )
    countermeasures = models.TextField(verbose_name=_('countermeasures'), blank=True)
    residual_risk = models.CharField(
        verbose_name=_('residual risk'),
        max_length=20,
        choices=RiskLevelChoices,
        blank=True,
    )
    # Where the two risks sit on the organisation's risk matrix (the risk_matrix setting): 1 is the lowest
    # likelihood or impact. Optional; with both given the matrix gives the risk level.
    unmitigated_likelihood = models.PositiveSmallIntegerField(
        verbose_name=_('unmitigated likelihood'), blank=True, null=True, validators=[MinValueValidator(1)],
    )
    unmitigated_impact = models.PositiveSmallIntegerField(
        verbose_name=_('unmitigated impact'), blank=True, null=True, validators=[MinValueValidator(1)],
    )
    residual_likelihood = models.PositiveSmallIntegerField(
        verbose_name=_('residual likelihood'), blank=True, null=True, validators=[MinValueValidator(1)],
    )
    residual_impact = models.PositiveSmallIntegerField(
        verbose_name=_('residual impact'), blank=True, null=True, validators=[MinValueValidator(1)],
    )
    tolerable_risk = models.CharField(
        verbose_name=_('tolerable risk'),
        max_length=20,
        choices=RiskLevelChoices,
        blank=True,
        help_text=_('The highest risk the organisation accepts here'),
    )
    document = models.URLField(verbose_name=_('document'), blank=True, help_text=_('Link to the full report'))

    clone_fields = ('zone', 'conduit', 'kind', 'method', 'tolerable_risk')

    class Meta:
        ordering = ('-assessed_on', 'pk')
        verbose_name = _('risk assessment')
        verbose_name_plural = _('risk assessments')

    def __str__(self):
        return f'{self.subject} {self.get_kind_display().split(" (")[0].lower()} {self.assessed_on}'

    @property
    def subject(self):
        return self.zone or self.conduit

    @property
    def residual_above_tolerable(self):
        order = RiskLevelChoices.values()
        if not self.residual_risk or not self.tolerable_risk:
            return False
        return order.index(self.residual_risk) > order.index(self.tolerable_risk)

    def clean(self):
        super().clean()
        if bool(self.zone_id) == bool(self.conduit_id):
            raise ValidationError(_('A risk assessment is of either a zone or a conduit.'))
        if self.status == RiskAssessmentStatusChoices.APPROVED and not self.approved_on:
            raise ValidationError({'approved_on': _('An approved assessment has an approval date.')})
        if self.approved_on and self.approved_on < self.assessed_on:
            raise ValidationError({'approved_on': _('Approved before it was assessed.')})
        # Likelihood and impact place a risk on the matrix, which then gives its level
        for which in ('unmitigated', 'residual'):
            likelihood, impact = getattr(self, f'{which}_likelihood'), getattr(self, f'{which}_impact')
            if bool(likelihood) != bool(impact):
                raise ValidationError({
                    f'{which}_impact' if likelihood else f'{which}_likelihood':
                        _('Likelihood and impact go together.'),
                })
            if not likelihood:
                continue
            level = risk.matrix_level(likelihood, impact)
            if level is None:
                raise ValidationError({f'{which}_likelihood': _('This is not on the risk matrix.')})
            if not getattr(self, f'{which}_risk'):
                setattr(self, f'{which}_risk', level)
            elif getattr(self, f'{which}_risk') != level:
                raise ValidationError({f'{which}_risk': _(
                    'The risk matrix gives {level} for this likelihood and impact. Leave the level empty to take '
                    'it from the matrix.').format(level=risk.LEVEL_LABELS[level])})

    def _place(self, which):
        likelihood, impact = getattr(self, f'{which}_likelihood'), getattr(self, f'{which}_impact')
        if not likelihood or not impact:
            return ''
        matrix = risk.get_matrix()
        try:
            return (f'{likelihood} - {matrix["likelihood"][likelihood - 1]}, '
                    f'{impact} - {matrix["impact"][impact - 1]}')
        except IndexError:
            return f'{likelihood}, {impact}'

    @property
    def unmitigated_place(self):
        return self._place('unmitigated')

    @property
    def residual_place(self):
        return self._place('residual')

    @property
    def current_step(self):
        """The IEC 62443-3-2 step this assessment is at, by its own fields; empty when nothing is left."""
        return risk.current_step(self)

    def get_status_color(self):
        return RiskAssessmentStatusChoices.colors.get(self.status)

    def get_residual_risk_color(self):
        return RiskLevelChoices.colors.get(self.residual_risk)


REQUIREMENT_IDENTIFIER = re.compile(r'^(SR|CR) (\d+)\.(\d+)(?: RE (\d+))?$')


class SystemRequirement(PrimaryModel):
    """
    An IEC 62443-3-3 system requirement (SR 1.1) or requirement enhancement (SR 1.1 RE 1), by identifier.

    The plugin ships identifiers and their foundational requirement only. The wording and the lowest security level
    at which a requirement applies are copyrighted parts of the standard: users load them from their own licensed
    copy (manage.py ot_requirements --csv), into their own database.
    """
    edition = models.CharField(
        verbose_name=_('edition'),
        max_length=20,
        choices=RequirementEditionChoices,
        default=RequirementEditionChoices.IEC_62443_3_3_2013,
    )
    identifier = models.CharField(
        verbose_name=_('identifier'),
        max_length=30,
        db_collation='natural_sort',
        help_text=_('e.g. SR 1.1, or SR 1.1 RE 1 for a requirement enhancement'),
    )
    foundational_requirement = models.CharField(
        verbose_name=_('foundational requirement'),
        max_length=10,
        choices=FoundationalRequirementChoices,
        blank=True,
        editable=False,
        help_text=_('Follows from the identifier: SR 1.x is FR 1 (IAC) ... SR 7.x is FR 7 (RA)'),
    )
    parent = models.ForeignKey(
        to='self',
        on_delete=models.PROTECT,
        related_name='enhancements',
        verbose_name=_('requirement'),
        blank=True,
        null=True,
        help_text=_('The system requirement this enhancement belongs to'),
    )
    security_level = models.PositiveSmallIntegerField(
        verbose_name=_('applies from SL'),
        blank=True,
        null=True,
        help_text=_('The lowest security level (1-4) at which the requirement applies, from your copy of the '
                    'standard; empty until loaded'),
    )
    wording = models.TextField(
        verbose_name=_('wording'),
        blank=True,
        help_text=_('From your licensed copy of the standard; never shipped with the plugin'),
    )

    clone_fields = ('edition', 'foundational_requirement', 'parent', 'security_level')

    class Meta:
        ordering = ('edition', 'identifier')
        verbose_name = _('system requirement')
        verbose_name_plural = _('system requirements')
        constraints = (
            models.UniqueConstraint(
                fields=('edition', 'identifier'),
                name='%(app_label)s_%(class)s_unique_edition_identifier',
                violation_error_message=_('This requirement already exists in this edition.'),
            ),
        )

    def __str__(self):
        return self.identifier

    @property
    def fr_index(self):
        """Position of the requirement's FR in a security level vector (0 for IAC ... 6 for RA)."""
        return FoundationalRequirementChoices.values().index(self.foundational_requirement)

    @property
    def is_enhancement(self):
        return ' RE ' in self.identifier

    def clean(self):
        super().clean()
        match = REQUIREMENT_IDENTIFIER.match(self.identifier or '')
        if not match:
            raise ValidationError({'identifier': _('Write it as SR 1.1, or SR 1.1 RE 1 for an enhancement.')})
        fr_number = int(match.group(2))
        frs = FoundationalRequirementChoices.values()
        if not 1 <= fr_number <= len(frs):
            raise ValidationError({'identifier': _('There are seven foundational requirements (SR 1.x to SR 7.x).')})
        self.foundational_requirement = frs[fr_number - 1]
        if match.group(4):
            base = f'{match.group(1)} {match.group(2)}.{match.group(3)}'
            if not self.parent_id or self.parent.identifier != base or self.parent.edition != self.edition:
                raise ValidationError({'parent': _('An enhancement belongs to {base} of the same edition.').format(
                    base=base)})
        elif self.parent_id:
            raise ValidationError({'parent': _('Only an enhancement (... RE n) has a parent requirement.')})
        if self.security_level is not None and not 1 <= self.security_level <= 4:
            raise ValidationError({'security_level': _('A security level from 1 to 4.')})

    def save(self, *args, **kwargs):
        if match := REQUIREMENT_IDENTIFIER.match(self.identifier or ''):
            self.foundational_requirement = FoundationalRequirementChoices.values()[int(match.group(2)) - 1]
        super().save(*args, **kwargs)

    def applies_at(self, levels):
        """True when this requirement applies at the security level vector `levels` (SL mapping loaded)."""
        return bool(levels) and self.security_level is not None and levels[self.fr_index] >= self.security_level


class RequirementStatus(PrimaryModel):
    """
    Where a zone or a conduit stands against one system requirement: met, met by a compensating countermeasure,
    not met or not applicable, with the evidence and who assessed it. This is what backs a zone's SL-A.
    """
    zone = models.ForeignKey(
        to=Zone,
        on_delete=models.PROTECT,
        related_name='requirement_statuses',
        verbose_name=_('zone'),
        blank=True,
        null=True,
    )
    conduit = models.ForeignKey(
        to=Conduit,
        on_delete=models.PROTECT,
        related_name='requirement_statuses',
        verbose_name=_('conduit'),
        blank=True,
        null=True,
    )
    requirement = models.ForeignKey(
        to=SystemRequirement,
        on_delete=models.PROTECT,
        related_name='statuses',
        verbose_name=_('requirement'),
    )
    status = models.CharField(
        verbose_name=_('status'),
        max_length=20,
        choices=RequirementStatusChoices,
    )
    countermeasure = models.TextField(
        verbose_name=_('compensating countermeasure'),
        blank=True,
        help_text=_('What compensates when the requirement is met by another measure'),
    )
    evidence = models.TextField(
        verbose_name=_('evidence'),
        blank=True,
        help_text=_('Configuration, test report, procedure, interview'),
    )
    risk_assessment = models.ForeignKey(
        to='netbox_ot.RiskAssessment',
        on_delete=models.SET_NULL,
        related_name='requirement_statuses',
        verbose_name=_('risk assessment'),
        blank=True,
        null=True,
    )
    assessed_by = models.ForeignKey(
        to='tenancy.Contact',
        on_delete=models.PROTECT,
        related_name='ot_requirement_statuses',
        verbose_name=_('assessed by'),
        blank=True,
        null=True,
    )
    assessed_on = models.DateField(verbose_name=_('assessed on'), blank=True, null=True)

    clone_fields = ('zone', 'conduit', 'status', 'risk_assessment', 'assessed_by', 'assessed_on')

    class Meta:
        ordering = ('zone', 'conduit', 'requirement')
        verbose_name = _('requirement status')
        verbose_name_plural = _('requirement statuses')
        constraints = (
            models.UniqueConstraint(
                fields=('zone', 'requirement'),
                condition=Q(zone__isnull=False),
                name='%(app_label)s_%(class)s_unique_zone_requirement',
                violation_error_message=_('This zone already has a status for this requirement.'),
            ),
            models.UniqueConstraint(
                fields=('conduit', 'requirement'),
                condition=Q(conduit__isnull=False),
                name='%(app_label)s_%(class)s_unique_conduit_requirement',
                violation_error_message=_('This conduit already has a status for this requirement.'),
            ),
        )

    def __str__(self):
        return f'{self.subject} {self.requirement}'

    @property
    def subject(self):
        return self.zone or self.conduit

    def clean(self):
        super().clean()
        if bool(self.zone_id) == bool(self.conduit_id):
            raise ValidationError(_('A requirement status is of either a zone or a conduit.'))
        if self.status == RequirementStatusChoices.COMPENSATED and not self.countermeasure.strip():
            raise ValidationError({'countermeasure': _('Name the countermeasure that compensates.')})
        if self.risk_assessment_id and (self.risk_assessment.zone_id, self.risk_assessment.conduit_id) != (
                self.zone_id, self.conduit_id):
            raise ValidationError({'risk_assessment': _('The risk assessment is of another zone or conduit.')})

    def get_status_color(self):
        return RequirementStatusChoices.colors.get(self.status)


class PluginSettings(models.Model):
    """
    The plugin's settings that an administrator changes in the GUI: one row.

    A plain Django model on purpose: without change logging, netbox-branching does not copy it into branches,
    so it lives in main and reads the same whichever branch is active.
    """
    branching_enabled = models.BooleanField(
        verbose_name=_('use a branch for imports'), default=False,
        help_text=_('The import and demo commands run in the default branch'),
    )
    default_branch = models.CharField(
        verbose_name=_('default branch'), max_length=100, blank=True,
        help_text=_('Name of a netbox-branching branch'),
    )
    protect_main = models.BooleanField(
        verbose_name=_('refuse imports into main'), default=False,
        help_text=_('The import and demo commands will not write to main'),
    )
    last_updated = models.DateTimeField(auto_now=True, null=True)
    updated_by = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = _('plugin settings')
        verbose_name_plural = _('plugin settings')

    def __str__(self):
        return str(_('OT settings'))

    @classmethod
    def load(cls):
        """The settings row, created with the defaults on first use."""
        return cls.objects.order_by('pk').first() or cls.objects.create()

    def clean(self):
        super().clean()
        if self.branching_enabled and not self.default_branch:
            raise ValidationError({'default_branch': _('Pick the branch that imports go to.')})
