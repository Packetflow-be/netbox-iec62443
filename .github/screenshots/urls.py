# Run with `manage.py shell < urls.py` after iec62443_demo: prints the demo plant's page URLs as JSON.
import json

from dcim.models import Site

from netbox_iec62443.models import Flow, Zone

site = Site.objects.get(slug='iec62443-demo')
print(json.dumps({
    'site': site.pk,
    'remote_flow': Flow.objects.get(name='MSP maintenance RDP').get_absolute_url(),
    'cell_zone': Zone.objects.get(site=site, slug='line-1-cell').get_absolute_url(),
}))
