/*
 * Access map diagram: zoom, pan, highlighting and the detail panel on top of the server-rendered SVG.
 * No library and nothing loaded from elsewhere; without this script the diagram is a plain picture with links.
 */
(function () {
  'use strict';

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function ([name, value]) {
      if (name === 'text') node.textContent = value;
      else node.setAttribute(name, value);
    });
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }

  function init() {
    const view = document.querySelector('.ot-map-view');
    const svg = view && view.querySelector('svg.ot-map');
    const source = document.getElementById('ot-map-data');
    if (!svg || !source || view.classList.contains('ot-map-live')) return;
    const data = JSON.parse(source.textContent);
    const labels = data.labels || {};
    const card = view.closest('.card');
    const panel = card.querySelector('.ot-map-panel');
    const width = Number(svg.dataset.width);
    const height = Number(svg.dataset.height);
    const MIN = 0.3, MAX = 2.5, READABLE = 0.8;
    let scale = 1;

    view.classList.add('ot-map-live');
    svg.style.maxWidth = 'none';
    card.querySelectorAll('.ot-map-tools, .ot-map-hint').forEach(function (node) { node.hidden = false; });

    // Zoom: the SVG is given a size and the view scrolls, so touch scrolling and scrollbars keep working
    function zoom(to, anchorX, anchorY) {
      const before = scale;
      scale = Math.min(MAX, Math.max(MIN, to));
      const ax = anchorX === undefined ? view.clientWidth / 2 : anchorX;
      const ay = anchorY === undefined ? view.clientHeight / 2 : anchorY;
      const x = (view.scrollLeft + ax) / before, y = (view.scrollTop + ay) / before;
      svg.setAttribute('width', Math.round(width * scale));
      svg.setAttribute('height', Math.round(height * scale));
      view.scrollLeft = x * scale - ax;
      view.scrollTop = y * scale - ay;
    }
    function fit(whole) {
      // The whole drawing, width and height, inside the view (capped at 80vh by the stylesheet): the lowest
      // level holds the controllers and must not be the part that is cut off. On first load no smaller than
      // readable; the Fit button always shows everything.
      const maxHeight = parseFloat(window.getComputedStyle(view).maxHeight) || window.innerHeight * 0.8;
      const all = Math.min(1, (view.clientWidth - 2) / width, (maxHeight - 2) / height);
      zoom(whole ? Math.max(MIN, all) : Math.max(Math.min(1, READABLE), all), 0, 0);
      view.scrollLeft = 0;
      view.scrollTop = 0;
    }
    fit(false);

    card.querySelectorAll('[data-map]').forEach(function (button) {
      button.addEventListener('click', function () {
        const action = button.dataset.map;
        if (action === 'in') zoom(scale * 1.25);
        else if (action === 'out') zoom(scale / 1.25);
        else if (action === 'fit') fit(true);
        else if (action === 'save') save();
      });
    });
    view.addEventListener('wheel', function (event) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const box = view.getBoundingClientRect();
      zoom(scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15), event.clientX - box.left, event.clientY - box.top);
    }, { passive: false });

    // Drag with the mouse to move (touch scrolls natively); a drag is not a click
    let drag = null, dragged = false;
    view.addEventListener('pointerdown', function (event) {
      if (event.pointerType !== 'mouse' || event.button !== 0) return;
      drag = { x: event.clientX, y: event.clientY, left: view.scrollLeft, top: view.scrollTop };
      dragged = false;
    });
    window.addEventListener('pointermove', function (event) {
      if (!drag) return;
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (!dragged && Math.abs(dx) + Math.abs(dy) < 5) return;
      dragged = true;
      view.classList.add('ot-map-drag');
      view.scrollLeft = drag.left - dx;
      view.scrollTop = drag.top - dy;
    });
    window.addEventListener('pointerup', function () {
      drag = null;
      view.classList.remove('ot-map-drag');
    });

    // Highlighting: a zone with its arrows and neighbours, or an arrow with its two zones
    function related(kind, key) {
      const nodes = new Set(), edges = new Set();
      if (kind === 'node') {
        nodes.add(key);
        Object.entries(data.edges).forEach(function ([id, edge]) {
          if (edge.src === key || edge.dst === key) {
            edges.add(id);
            nodes.add(edge.src);
            nodes.add(edge.dst);
          }
        });
      } else if (data.edges[key]) {
        edges.add(key);
        nodes.add(data.edges[key].src);
        nodes.add(data.edges[key].dst);
      }
      return { nodes: nodes, edges: edges };
    }
    function highlight(kind, key) {
      svg.querySelectorAll('.ot-hl, .ot-sel').forEach(function (node) { node.classList.remove('ot-hl', 'ot-sel'); });
      svg.classList.toggle('ot-dim', Boolean(kind));
      if (!kind) return;
      const set = related(kind, key);
      svg.querySelectorAll('.ot-node').forEach(function (node) {
        node.classList.toggle('ot-hl', set.nodes.has(node.dataset.node));
        node.classList.toggle('ot-sel', kind === 'node' && node.dataset.node === key);
      });
      svg.querySelectorAll('.ot-edge, .ot-badge').forEach(function (node) {
        node.classList.toggle('ot-hl', set.edges.has(node.dataset.edge));
      });
    }

    function badge(verdict) {
      const color = { no: 'danger', expired: 'danger', unknown: 'warning', yes: 'success' }[verdict] || 'secondary';
      return el('span', { class: 'badge text-bg-' + color, text: (labels.verdicts || {})[verdict] || verdict });
    }
    function zoneLink(key) {
      const zone = data.nodes[key];
      return el('a', { href: zone.url, text: zone.name });
    }
    function rows(edges, inside) {
      const body = el('tbody');
      edges.forEach(function (edge) {
        edge.flows.forEach(function (flow) {
          body.appendChild(el('tr', {}, [
            el('td', {}, [edge.src ? zoneLink(edge.src) : null]),
            el('td', {}, [edge.dst ? zoneLink(edge.dst) : null]),
            el('td', {}, [el('a', { href: flow.url, text: flow.name })]),
            el('td', {}, [
              document.createTextNode([flow.protocol, flow.ports, flow.connection].filter(Boolean).join(' ')),
              flow.remote ? el('span', { class: 'badge text-bg-secondary ms-1', text: labels.remote }) : null,
            ]),
            el('td', {}, [badge(flow.verdict)]),
          ]));
        });
      });
      if (inside && inside.length) {
        body.appendChild(el('tr', {}, [el('th', { colspan: '5', text: labels.inside })]));
        inside.forEach(function (flow) {
          body.appendChild(el('tr', {}, [
            el('td', { colspan: '2' }),
            el('td', {}, [el('a', { href: flow.url, text: flow.name })]),
            el('td', { text: [flow.protocol, flow.ports, flow.connection].filter(Boolean).join(' ') }),
            el('td', {}, [badge(flow.verdict)]),
          ]));
        });
      }
      const head = el('thead', {}, [el('tr', {}, [labels.from, labels.to, labels.flow, labels.protocol, labels.verdict]
        .map(function (text) { return el('th', { text: text }); }))]);
      return el('div', { class: 'table-responsive' }, [el('table', { class: 'table table-sm table-hover' }, [head, body])]);
    }

    let selected = null;
    function show(kind, key) {
      selected = kind ? [kind, key] : null;
      highlight(kind, key);
      panel.replaceChildren();
      panel.hidden = !kind;
      if (!kind) return;
      const close = el('button', { type: 'button', class: 'btn-close', 'aria-label': labels.close });
      close.addEventListener('click', function () { show(null); });
      let head, edges, inside = null;
      if (kind === 'node') {
        const zone = data.nodes[key];
        edges = Object.values(data.edges).filter(function (edge) { return edge.src === key || edge.dst === key; });
        inside = zone.inside;
        const count = edges.reduce(function (n, edge) { return n + edge.flows.length; }, 0) + inside.length;
        const url = new URL(window.location.href);
        url.searchParams.delete('zone_id');
        url.searchParams.set('zone_id', zone.id);
        head = [
          el('strong', { text: zone.name + ' (' + count + ' ' + labels.flows + ')' }),
          el('a', { href: url.toString(), class: 'btn btn-sm btn-outline-primary', text: labels.focus }),
          el('a', { href: zone.url, class: 'btn btn-sm btn-outline-secondary', text: labels.open }),
          close,
        ];
      } else {
        const edge = data.edges[key];
        edges = [edge];
        head = [
          el('strong', { text: data.nodes[edge.src].name + ' → ' + data.nodes[edge.dst].name +
            ' (' + edge.flows.length + ' ' + labels.flows + ')' }),
          close,
        ];
      }
      panel.appendChild(el('div', { class: 'ot-map-panel-head' }, head));
      if (kind === 'node' && data.nodes[key].members.length) {
        const list = el('div', { class: 'px-3 pb-2 small' }, [el('span', { class: 'text-muted', text: labels.subzones + ': ' })]);
        data.nodes[key].members.forEach(function (zone, i) {
          if (i) list.appendChild(document.createTextNode(', '));
          list.appendChild(el('a', { href: zone.url, text: zone.name }));
        });
        panel.appendChild(list);
      }
      if (edges.length || (inside && inside.length)) panel.appendChild(rows(edges, inside));
      else panel.appendChild(el('div', { class: 'px-3 pb-2 text-muted', text: labels.none }));
    }

    function target(event) {
      const node = event.target.closest('.ot-node, .ot-edge, .ot-badge');
      if (!node || !svg.contains(node)) return null;
      return node.dataset.node ? ['node', node.dataset.node] : ['edge', node.dataset.edge];
    }
    svg.addEventListener('click', function (event) {
      if (dragged) {
        event.preventDefault();
        dragged = false;
        return;
      }
      const hit = target(event);
      if (hit) event.preventDefault();  // a zone is a link without this script; here it opens the panel
      if (hit && selected && hit[0] === selected[0] && hit[1] === selected[1]) show(null);
      else show.apply(null, hit || [null]);
    });
    svg.addEventListener('mouseover', function (event) {
      if (selected || drag) return;
      highlight.apply(null, target(event) || [null]);
    });
    svg.addEventListener('mouseleave', function () {
      if (!selected) highlight(null);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && selected) show(null);
    });

    // The diagram as a file, for a report: the SVG as the server made it, without the highlighting
    function save() {
      const copy = svg.cloneNode(true);
      copy.classList.remove('ot-dim');
      copy.querySelectorAll('.ot-hl, .ot-sel').forEach(function (node) { node.classList.remove('ot-hl', 'ot-sel'); });
      copy.setAttribute('width', width);
      copy.setAttribute('height', height);
      copy.removeAttribute('style');
      copy.querySelectorAll('a[href]').forEach(function (a) { a.setAttribute('href', new URL(a.getAttribute('href'), window.location.href)); });
      const blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy)],
        { type: 'image/svg+xml' });
      const link = el('a', { href: URL.createObjectURL(blob), download: 'access-map.svg' });
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  // NetBox swaps page content with HTMX on some navigations
  document.addEventListener('htmx:afterSettle', init);
})();
