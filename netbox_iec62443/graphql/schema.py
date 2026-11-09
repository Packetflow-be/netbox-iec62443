import strawberry
import strawberry_django

from .types import ConduitType, ZoneType


@strawberry.type(name='Query')
class IEC62443Query:
    iec62443_zone: ZoneType = strawberry_django.field()
    iec62443_zone_list: list[ZoneType] = strawberry_django.field()

    iec62443_conduit: ConduitType = strawberry_django.field()
    iec62443_conduit_list: list[ConduitType] = strawberry_django.field()


schema = [IEC62443Query]
