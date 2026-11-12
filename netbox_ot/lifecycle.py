"""
End of support per asset, read from the companion plugin netbox-lifecycle when it is installed (a hardware
lifecycle on a device type or module type). netbox-ot never requires it: without it everything here returns
nothing.

A device's dates are the earliest of its device type and the module types of its installed modules (a PLC's CPU
is usually a module). The date that counts for security is the end of security fixes when known, else the end
of support.
"""
import datetime
from dataclasses import dataclass

from django.apps import apps
from django.utils import timezone

LIFECYCLE_APP = 'netbox_lifecycle'
# A date within this many days counts as "ahead"
AHEAD_DAYS = 365


def installed():
    return apps.is_installed(LIFECYCLE_APP)


@dataclass
class EndOfSupport:
    date: datetime.date        # end of security fixes, else end of support
    kind: str                  # 'security' or 'support'
    source: object             # the device type or module type it comes from
    lifecycle: object          # the netbox-lifecycle HardwareLifecycle

    @property
    def passed(self):
        return self.date < timezone.localdate()

    @property
    def ahead(self):
        today = timezone.localdate()
        return today <= self.date <= today + datetime.timedelta(days=AHEAD_DAYS)

    @property
    def color(self):
        return 'red' if self.passed else 'orange' if self.ahead else 'green'


def _end(lifecycle, source):
    if lifecycle.end_of_security:
        return EndOfSupport(lifecycle.end_of_security, 'security', source, lifecycle)
    if lifecycle.end_of_support:
        return EndOfSupport(lifecycle.end_of_support, 'support', source, lifecycle)
    return None


def end_of_support(devices):
    """{device pk: EndOfSupport} for the devices that have a lifecycle date, the earliest that applies."""
    devices = [d for d in devices if getattr(d, '_meta', None) and d._meta.label_lower == 'dcim.device']
    if not installed() or not devices:
        return {}
    from django.contrib.contenttypes.models import ContentType

    from dcim.models import DeviceType, Module, ModuleType
    HardwareLifecycle = apps.get_model(LIFECYCLE_APP, 'HardwareLifecycle')

    device_type_ids = {d.device_type_id for d in devices}
    modules = list(Module.objects.filter(device__in=devices).select_related('module_type'))
    module_type_ids = {m.module_type_id for m in modules}
    dt_type = ContentType.objects.get_for_model(DeviceType)
    mt_type = ContentType.objects.get_for_model(ModuleType)
    by_device_type, by_module_type = {}, {}
    for lc in HardwareLifecycle.objects.filter(assigned_object_type=dt_type, assigned_object_id__in=device_type_ids):
        by_device_type[lc.assigned_object_id] = lc
    for lc in HardwareLifecycle.objects.filter(assigned_object_type=mt_type, assigned_object_id__in=module_type_ids):
        by_module_type[lc.assigned_object_id] = lc
    module_types = {}
    for m in modules:
        module_types.setdefault(m.device_id, {})[m.module_type_id] = m.module_type

    result = {}
    for device in devices:
        candidates = []
        if device.device_type_id in by_device_type:
            candidates.append(_end(by_device_type[device.device_type_id], device.device_type))
        for type_id, module_type in module_types.get(device.pk, {}).items():
            if type_id in by_module_type:
                candidates.append(_end(by_module_type[type_id], module_type))
        candidates = [c for c in candidates if c]
        if candidates:
            result[device.pk] = min(candidates, key=lambda c: c.date)
    return result
