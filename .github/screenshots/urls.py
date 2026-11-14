# Run with `manage.py shell < urls.py` after ot_demo: prints the demo plant's page URLs as JSON.
import json

from dcim.models import Site

from netbox_ot.models import Flow, RiskAssessment, Zone

site = Site.objects.get(slug='iec62443-demo')
cell = Zone.objects.get(site=site, slug='line-1-cell')
print(json.dumps({
    'site': site.pk,
    'remote_flow': Flow.objects.get(name='MSP maintenance RDP').get_absolute_url(),
    'cell_zone': cell.get_absolute_url(),
    'risk_assessment': RiskAssessment.objects.filter(zone=cell, kind='detailed').first().get_absolute_url(),
}))
