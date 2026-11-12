# Access map

![Access map tab on a site: flows into the controller zones, what needs attention, and a diagram](access-map.png)

The access map answers one question per site: **who can reach the controllers, and did someone decide that
is allowed?**

- It lists every flow into zones at Purdue level 2 or below. The level is selectable (≤ 0 ... ≤ 5), and its
  default is the `access_map_max_level` setting.
- Flows are ordered by what needs action: not allowed first, then allowed but expired, unknown, and allowed.
- Each row shows the source and destination zone with their levels, the protocol and ports, the access the
  requests had (read, write, control, program), the hops it runs through, remote access, the verdict, when the
  flow was last seen and the evidence.
- **Needs attention** sums up expired access, verdicts due for review, flows not seen for `stale_after_days`
  (default 90), flows that run outside any documented conduit, and flows that reach their zone over a connection
  opened from inside it (reverse connect, a broker: see [Connection models](data-model.md#connection-models)).
- A flow with another [connection model](data-model.md#connection-models) than client/server shows it under the
  protocol, with the broker's zone and the topics.
- A small server-rendered **diagram** draws the zones by Purdue level with one arrow per zone pair: red for
  not allowed or expired, amber for unknown, green for allowed; dashed for remote access, dotted when the
  destination opens the connection itself. Arrows point from the side that acts to the side acted upon. The
  number on an arrow is how many flows it carries.

It is an *Access map* tab on the site page and a standalone page under *OT > Access map*. It needs the
`view_flow` permission.

## API

`GET /api/plugins/ot/access-map/?site_id=<id>[&max_level=<level>]` returns the site's access map as
data, for reports and other tools: the flows into zones at that Purdue level or below, in access-map order,
as full flow objects with their hops. Needs `view_flow` and view access to the site. The diagram is only on
the page, not in the API.
