from netbox.search import SearchIndex

from .models import (
    Conduit,
    Fieldbus,
    Flow,
    IndustrialService,
    RequirementStatus,
    RiskAssessment,
    SystemRequirement,
    Zone,
)


class ZoneIndex(SearchIndex):
    model = Zone
    fields = (
        ('name', 100),
        ('slug', 110),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'zone_type', 'purdue_level', 'accountable', 'description')


class ConduitIndex(SearchIndex):
    model = Conduit
    fields = (
        ('name', 100),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'accountable', 'description')


class FlowIndex(SearchIndex):
    model = Flow
    fields = (
        ('name', 100),
        ('description', 500),
        ('evidence', 2000),
        ('comments', 5000),
    )
    display_attrs = ('source_zone', 'destination_zone', 'protocol', 'allowed', 'remote_access', 'conduit')


class FieldbusIndex(SearchIndex):
    model = Fieldbus
    fields = (
        ('name', 100),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('site', 'zone', 'medium', 'protocol', 'gateway')


class IndustrialServiceIndex(SearchIndex):
    model = IndustrialService
    fields = (
        ('address', 300),
        ('description', 500),
        ('evidence', 2000),
        ('comments', 5000),
    )
    display_attrs = ('device', 'virtual_machine', 'protocol', 'role', 'fieldbus')


class RiskAssessmentIndex(SearchIndex):
    model = RiskAssessment
    fields = (
        ('method', 300),
        ('description', 500),
        ('threats', 2000),
        ('vulnerabilities', 2000),
        ('consequences', 2000),
        ('countermeasures', 2000),
        ('comments', 5000),
    )
    display_attrs = ('zone', 'conduit', 'kind', 'status', 'assessed_on', 'residual_risk')


class SystemRequirementIndex(SearchIndex):
    model = SystemRequirement
    fields = (
        ('identifier', 100),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('edition', 'foundational_requirement', 'security_level')


class RequirementStatusIndex(SearchIndex):
    model = RequirementStatus
    fields = (
        ('countermeasure', 2000),
        ('evidence', 2000),
        ('description', 500),
        ('comments', 5000),
    )
    display_attrs = ('zone', 'conduit', 'requirement', 'status')


indexes = (
    ZoneIndex, ConduitIndex, FlowIndex, RiskAssessmentIndex, SystemRequirementIndex, RequirementStatusIndex,
    FieldbusIndex, IndustrialServiceIndex,
)
