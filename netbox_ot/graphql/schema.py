import strawberry
import strawberry_django

from .types import (
    ConduitType,
    FieldbusType,
    FlowHopType,
    FlowType,
    IndustrialServiceType,
    RiskAssessmentType,
    ZoneType,
)


@strawberry.type(name='Query')
class IEC62443Query:
    ot_zone: ZoneType = strawberry_django.field()
    ot_zone_list: list[ZoneType] = strawberry_django.field()

    ot_conduit: ConduitType = strawberry_django.field()
    ot_conduit_list: list[ConduitType] = strawberry_django.field()

    ot_flow: FlowType = strawberry_django.field()
    ot_flow_list: list[FlowType] = strawberry_django.field()

    ot_flow_hop: FlowHopType = strawberry_django.field()
    ot_flow_hop_list: list[FlowHopType] = strawberry_django.field()

    ot_risk_assessment: RiskAssessmentType = strawberry_django.field()
    ot_risk_assessment_list: list[RiskAssessmentType] = strawberry_django.field()

    ot_fieldbus: FieldbusType = strawberry_django.field()
    ot_fieldbus_list: list[FieldbusType] = strawberry_django.field()

    ot_industrial_service: IndustrialServiceType = strawberry_django.field()
    ot_industrial_service_list: list[IndustrialServiceType] = strawberry_django.field()


schema = [IEC62443Query]
