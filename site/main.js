(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Nav border on scroll
  const nav = document.querySelector('.nav');
  const onScroll = () => nav.classList.toggle('scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // Scroll reveal
  const els = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) els.forEach(e => e.classList.add('in'));
  else {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    }), { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    els.forEach(e => io.observe(e));
  }

  // Carousel: CSS scroll-snap + arrows, dots, autoplay
  const root = document.querySelector('.carousel');
  if (root) {
    const track = root.querySelector('.track');
    const slides = [...track.children];
    const dotsBox = root.querySelector('.dots');
    let current = 0, timer = null, paused = false, stopped = false;
    const dots = slides.map((s, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-label', `Show screenshot ${i + 1}: ${s.querySelector('p').textContent}`);
      b.addEventListener('click', () => { stop(); go(i); });
      dotsBox.appendChild(b); return b;
    });
    const behavior = () => (reduce ? 'auto' : 'smooth');
    function go(i) {
      i = (i + slides.length) % slides.length;
      const s = slides[i];
      track.scrollTo({ left: s.offsetLeft - (track.clientWidth - s.offsetWidth) / 2, behavior: behavior() });
    }
    function mark(i) {
      current = i;
      slides.forEach((s, j) => { s.classList.toggle('active', j === i); });
      dots.forEach((d, j) => d.setAttribute('aria-current', j === i ? 'true' : 'false'));
    }
    // Active slide = the one nearest the track centre
    let raf = 0;
    track.addEventListener('scroll', () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const mid = track.scrollLeft + track.clientWidth / 2;
        let best = 0, bd = Infinity;
        slides.forEach((s, j) => { const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid); if (d < bd) { bd = d; best = j; } });
        if (best !== current || !slides[best].classList.contains('active')) mark(best);
      });
    }, { passive: true });
    root.querySelector('.prev').addEventListener('click', () => { stop(); go(current - 1); });
    root.querySelector('.next').addEventListener('click', () => { stop(); go(current + 1); });
    track.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') { e.preventDefault(); stop(); go(current + 1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); stop(); go(current - 1); }
    });
    // Autoplay: pauses on hover/focus, stops after the user interacts
    const stop = () => { stopped = true; clearInterval(timer); };
    const tick = () => { if (!paused && !stopped && !document.hidden && inView) go(current + 1); };
    let inView = false;
    new IntersectionObserver(([e]) => { inView = e.isIntersecting; }, { threshold: 0.4 }).observe(root);
    ['pointerdown', 'touchstart', 'wheel'].forEach(t => track.addEventListener(t, stop, { passive: true }));
    root.addEventListener('mouseenter', () => paused = true);
    root.addEventListener('mouseleave', () => paused = false);
    root.addEventListener('focusin', () => paused = true);
    root.addEventListener('focusout', () => paused = false);
    mark(0);
    if (!reduce) timer = setInterval(tick, 3200);
  }

  // Import Sankey: sources → parsed kinds → app surfaces
  const sankeyRoot = document.getElementById('sankey');
  const sankeyDetail = document.getElementById('sankey-detail');
  if (sankeyRoot && sankeyDetail) {
    const NS = 'http://www.w3.org/2000/svg';
    const introHTML = sankeyDetail.innerHTML;
    const tone = { flights: '#FF7A59', stays: '#E8A87C', rentals: '#FF8D9A', drives: '#E8C36A' };
    const nodes = [
      { id: 'flighty', col: 0, label: 'Flighty CSV', kicker: 'Source',
        text: 'The CSV from Flighty Settings: airline, route, gates, times, aircraft, PNR, seat, and Flighty\'s flight id. Diversions use the diversion airport.' },
      { id: 'wallet', col: 0, label: 'Wallet pass', kicker: 'Source',
        text: 'A boarding-pass <code>.pkpass</code> with an IATA barcode: PNR, route, carrier, flight number, cabin and seat. Each leg of a multi-leg pass becomes its own flight.' },
      { id: 'calendar', col: 0, label: 'Calendar', kicker: 'Source',
        text: '<code>.ics</code> from Google, Outlook, Apple or TripIt, or a <code>webcal://</code> feed. Titles classify as flight, rental or stay; the event UID is the <code>external_id</code>.' },
      { id: 'email', col: 0, label: 'Email', kicker: 'Source',
        text: 'A forwarded <code>.eml</code> or pasted text. Email-in runs the same parsers on the body plus <code>.ics</code>, <code>.pkpass</code>, PDF and <code>.eml</code> attachments.' },
      { id: 'csv', col: 0, label: 'Any CSV', kicker: 'Source',
        text: 'Send the file once for columns, samples and a guessed mapping, then again with <code>csv_kind</code> of flight, rental or lodging.' },
      { id: 'typed', col: 0, label: 'Typed in', kicker: 'Source',
        text: 'Type a flight, stay or rental in the app. Expenses you add or split, and photo thumbnails from a trip, land here too.' },
      { id: 'timeline', col: 0, label: 'Timeline', kicker: 'Source',
        text: '<code>Timeline.json</code> from the phone, or an older Takeout Semantic Location History month. Driving segments keep path, distance and stops, private to you.' },
      { id: 'flights', col: 1, label: 'Flights', kicker: 'Parsed',
        text: 'Number, route, times, seat, cabin, PNR, aircraft, delay and status. Email layouts cover major airlines and agencies.' },
      { id: 'stays', col: 1, label: 'Stays', kicker: 'Parsed',
        text: 'Name, check-in/out, nights, rooms, guests, totals, address, brand and booking source. Templates cover Booking.com, Airbnb, Hotels.com, Concur and hotel folios.' },
      { id: 'rentals', col: 1, label: 'Rentals', kicker: 'Parsed',
        text: 'Company, confirmation, pickup and return, vehicle class, mileage and cost. Avis, Enterprise and Hertz receipts parse first; Budget- and National-style mail follow generic rules.' },
      { id: 'drives', col: 1, label: 'Drives', kicker: 'Parsed',
        text: 'Driving segments from Google Maps Timeline, with a thinned path, distance and short stops. A rental\'s recorded miles win when a drive overlaps that rental.' },
      { id: 'live', col: 2, label: 'Live status', kicker: 'In the app',
        text: 'Bring your own AeroDataBox, Aviationstack or FlightAware key for gate, terminal, delay and baggage belt.' },
      { id: 'itinerary', col: 2, label: 'Itinerary', kicker: 'In the app',
        text: 'Flights, stays and rentals attach to a covering trip (one day of slack), or the trip you pass on commit. They show in Today, the itinerary, search and trip stories.' },
      { id: 'maps', col: 2, label: 'Maps', kicker: 'In the app',
        text: 'Flight routes and Timeline drives draw on the trip and journey maps. Story items can hide a driving day or add a note.' },
      { id: 'log', col: 2, label: "Driver's Log", kicker: 'In the app',
        text: 'Rental mileage and Timeline drive miles feed the Driver\'s Log and year-in-travel stats. A rental\'s recorded miles win in the same pickup–dropoff window.' },
    ];
    const links = [
      { source: 'flighty', target: 'flights', value: 5, kicker: 'Flighty → Flights',
        text: 'Column names match what independent Flighty importers already read. <code>Flight Flighty ID</code> becomes <code>external_id</code>.' },
      { source: 'wallet', target: 'flights', value: 4, kicker: 'Wallet → Flights',
        text: 'IATA barcode first, then the pass display fields. Share the pass from the airline app or email.' },
      { source: 'calendar', target: 'flights', value: 3, kicker: 'Calendar → Flights',
        text: 'A flight number such as UA837 plus two airport codes, as in SFO to NRT or (SFO) … (SEA).' },
      { source: 'calendar', target: 'stays', value: 3, kicker: 'Calendar → Stays',
        text: '"Stay at …", "hotel", "check-in", or a hotel brand in the event title, location or description.' },
      { source: 'calendar', target: 'rentals', value: 2, kicker: 'Calendar → Rentals',
        text: '"Car rental" / "rental car", or a company (Hertz, Avis, Enterprise, …) together with car, pickup or return words.' },
      { source: 'email', target: 'flights', value: 4, kicker: 'Email → Flights',
        text: 'Known airline and agency layouts first, then a flight number plus two airport codes nearby.' },
      { source: 'email', target: 'stays', value: 5, kicker: 'Email → Stays',
        text: 'Booking.com, Airbnb, Hotels.com, Capital One Travel, Concur/BCD, and hotel folios. Cancellations come back with status cancelled.' },
      { source: 'email', target: 'rentals', value: 5, kicker: 'Email → Rentals',
        text: 'Vendored receipt templates for Avis, Enterprise and Hertz, plus generic rules for Budget- and National-style mail.' },
      { source: 'csv', target: 'flights', value: 2, kicker: 'CSV → Flights',
        text: 'Map columns onto flight number, departure airport, arrival airport and departure time.' },
      { source: 'csv', target: 'stays', value: 2, kicker: 'CSV → Stays',
        text: 'Map columns onto name and check-in. Dates accept ISO, US and "Jun 5, 2026".' },
      { source: 'csv', target: 'rentals', value: 2, kicker: 'CSV → Rentals',
        text: 'Map columns onto rental company and pickup time.' },
      { source: 'typed', target: 'flights', value: 1, kicker: 'Typed in → Flights',
        text: 'Add a flight in the app.' },
      { source: 'typed', target: 'stays', value: 1, kicker: 'Typed in → Stays',
        text: 'Add a stay in the app.' },
      { source: 'typed', target: 'rentals', value: 1, kicker: 'Typed in → Rentals',
        text: 'Add a rental in the app, including mileage for the Driver\'s Log.' },
      { source: 'typed', target: 'drives', value: 1, kicker: 'Typed in → Drives',
        text: 'Attach or dismiss rental matches by hand.' },
      { source: 'timeline', target: 'drives', value: 5, kicker: 'Timeline → Drives',
        text: 'Driving segments of 0.3 mi and up. Ones less than 30 minutes apart are merged.' },
      { source: 'flights', target: 'live', value: 4, kicker: 'Flights → Live status',
        text: 'The server asks the provider from two days before departure until a day after, and caches the answer.' },
      { source: 'flights', target: 'itinerary', value: 10, kicker: 'Flights → Itinerary',
        text: 'Same <code>external_id</code>, or the same flight number or route on the same day, is treated as a duplicate.' },
      { source: 'flights', target: 'maps', value: 5, kicker: 'Flights → Maps',
        text: 'Origin and destination airports plot the route on the trip and journey maps.' },
      { source: 'stays', target: 'itinerary', value: 11, kicker: 'Stays → Itinerary',
        text: 'Same <code>external_id</code> or confirmation, or the same name on the same check-in day, is treated as a duplicate.' },
      { source: 'rentals', target: 'itinerary', value: 4, kicker: 'Rentals → Itinerary',
        text: 'Pickup and return sit on the day-by-day itinerary next to flights and stays.' },
      { source: 'rentals', target: 'log', value: 6, kicker: "Rentals → Driver's Log",
        text: 'Mileage and cost roll into the Driver\'s Log and year-in-travel stats.' },
      { source: 'drives', target: 'maps', value: 3, kicker: 'Drives → Maps',
        text: 'One story item per driving day, with a polyline per drive and the stops in between.' },
      { source: 'drives', target: 'log', value: 3, kicker: "Drives → Driver's Log",
        text: 'Timeline miles count unless a linked rental already recorded them for that window.' },
    ];

    const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
    links.forEach((l, i) => {
      l.i = i;
      l.sourceNode = byId[l.source];
      l.targetNode = byId[l.target];
      l.kind = l.sourceNode.col === 1 ? l.source : l.target;
      l.color = tone[l.kind] || '#FF7A59';
    });
    nodes.forEach(n => {
      n.sourceLinks = links.filter(l => l.source === n.id);
      n.targetLinks = links.filter(l => l.target === n.id);
      const out = n.sourceLinks.reduce((s, l) => s + l.value, 0);
      const inn = n.targetLinks.reduce((s, l) => s + l.value, 0);
      n.value = Math.max(out, inn, 1);
    });

    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 1100 560');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    const gLinks = document.createElementNS(NS, 'g');
    const gNodes = document.createElementNS(NS, 'g');
    svg.append(gLinks, gNodes);
    sankeyRoot.append(svg);

    const pathEls = [];
    const nodeEls = new Map();
    let pinned = null;

    function ribbon(l) {
      const x0 = l.sourceNode.x + l.sourceNode.w;
      const x1 = l.targetNode.x;
      const y0 = l.sy, y1 = l.ty, dy = Math.max(l.dy, 1.5);
      const c = (x1 - x0) / 2;
      return `M${x0},${y0}C${x0 + c},${y0} ${x1 - c},${y1} ${x1},${y1}L${x1},${y1 + dy}C${x1 - c},${y1 + dy} ${x0 + c},${y0 + dy} ${x0},${y0 + dy}Z`;
    }

    function layout() {
      const W = 1100, H = 560, nodeW = 136, gap = 14, pad = 10;
      const xs = [8, (W - nodeW) / 2, W - nodeW - 8];
      let ky = Infinity;
      [0, 1, 2].forEach(c => {
        const ns = nodes.filter(n => n.col === c);
        const gaps = gap * Math.max(ns.length - 1, 0);
        const sum = ns.reduce((s, n) => s + n.value, 0);
        ky = Math.min(ky, (H - 2 * pad - gaps) / sum);
      });
      [0, 1, 2].forEach(c => {
        const ns = nodes.filter(n => n.col === c);
        const sumH = ns.reduce((s, n) => s + n.value * ky, 0) + gap * (ns.length - 1);
        let y = (H - sumH) / 2;
        ns.forEach(n => {
          n.x = xs[c]; n.y = y; n.w = nodeW; n.h = n.value * ky;
          y += n.h + gap;
        });
      });
      nodes.forEach(n => {
        n.sourceLinks.sort((a, b) => a.targetNode.y - b.targetNode.y);
        n.targetLinks.sort((a, b) => a.sourceNode.y - b.sourceNode.y);
      });
      nodes.forEach(n => {
        let y = n.y;
        n.sourceLinks.forEach(l => { l.sy = y; l.dy = l.value * ky; y += l.dy; });
        y = n.y;
        n.targetLinks.forEach(l => { l.ty = y; l.dy = l.value * ky; y += l.dy; });
      });
    }

    function el(name, attrs) {
      const n = document.createElementNS(NS, name);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      return n;
    }

    function draw() {
      layout();
      gLinks.replaceChildren();
      gNodes.replaceChildren();
      pathEls.length = 0;
      nodeEls.clear();
      links.forEach(l => {
        const p = el('path', { class: 'sankey-link', d: ribbon(l), fill: l.color, tabindex: '0', role: 'button', focusable: 'true' });
        p.setAttribute('aria-label', l.kicker);
        p.addEventListener('pointerenter', () => hover({ type: 'link', item: l }));
        p.addEventListener('pointerleave', () => hover(null));
        p.addEventListener('focus', () => hover({ type: 'link', item: l }));
        p.addEventListener('click', e => { e.stopPropagation(); pin({ type: 'link', item: l }); });
        p.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pin({ type: 'link', item: l }); } });
        gLinks.append(p);
        pathEls.push(p);
      });
      nodes.forEach(n => {
        const g = el('g', { class: 'sankey-node', tabindex: '0', role: 'button', focusable: 'true' });
        g.setAttribute('aria-label', n.label);
        g.append(
          el('rect', { x: n.x, y: n.y, width: n.w, height: n.h, rx: 10 }),
        );
        const t = el('text', { x: n.x + 12, y: n.y + n.h / 2, 'dominant-baseline': 'middle' });
        t.textContent = n.label;
        g.append(t);
        g.addEventListener('pointerenter', () => hover({ type: 'node', item: n }));
        g.addEventListener('pointerleave', () => hover(null));
        g.addEventListener('focus', () => hover({ type: 'node', item: n }));
        g.addEventListener('click', e => { e.stopPropagation(); pin({ type: 'node', item: n }); });
        g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pin({ type: 'node', item: n }); } });
        gNodes.append(g);
        nodeEls.set(n.id, g);
      });
      paint(pinned);
    }

    function related(sel) {
      if (!sel) return { nodes: new Set(), links: new Set() };
      if (sel.type === 'link') {
        return { nodes: new Set([sel.item.source, sel.item.target]), links: new Set([sel.item.i]) };
      }
      const start = sel.item;
      const ns = new Set([start.id]);
      const ls = new Set();
      const walk = (id, dir) => {
        const bag = dir === 'out' ? byId[id].sourceLinks : byId[id].targetLinks;
        bag.forEach(l => {
          ls.add(l.i);
          const next = dir === 'out' ? l.target : l.source;
          if (!ns.has(next)) { ns.add(next); walk(next, dir); }
        });
      };
      if (start.col === 0) walk(start.id, 'out');
      else if (start.col === 2) walk(start.id, 'in');
      else { walk(start.id, 'in'); walk(start.id, 'out'); }
      return { nodes: ns, links: ls };
    }

    function paint(sel) {
      const hot = related(sel);
      sankeyRoot.classList.toggle('is-hot', !!sel);
      pathEls.forEach((p, i) => p.classList.toggle('is-on', hot.links.has(i)));
      nodeEls.forEach((g, id) => g.classList.toggle('is-on', hot.nodes.has(id)));
    }

    function describe(sel) {
      if (!sel) { sankeyDetail.innerHTML = introHTML; return; }
      const it = sel.item;
      sankeyDetail.innerHTML = `<p class="sankey-kicker">${it.kicker}</p><h3>${it.label || it.kicker}</h3><p>${it.text}</p>`;
    }

    function same(a, b) {
      return a && b && a.type === b.type && a.item === b.item;
    }
    function hover(sel) {
      if (pinned) return;
      paint(sel);
      describe(sel);
    }
    function pin(sel) {
      pinned = same(pinned, sel) ? null : sel;
      paint(pinned);
      describe(pinned);
    }

    sankeyRoot.addEventListener('pointerleave', () => { if (!pinned) { paint(null); describe(null); } });
    document.addEventListener('click', e => {
      if (pinned && !sankeyRoot.contains(e.target) && !sankeyDetail.contains(e.target)) {
        pinned = null; paint(null); describe(null);
      }
    });
    addEventListener('keydown', e => {
      if (e.key === 'Escape' && pinned) { pinned = null; paint(null); describe(null); }
    });

    draw();
  }

  // Copy buttons
  document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', async () => {
    const text = document.getElementById(b.dataset.copy).innerText.trim();
    try { await navigator.clipboard.writeText(text); b.textContent = 'Copied'; b.classList.add('done'); }
    catch { b.textContent = 'Press ⌘C'; const r = document.createRange(); r.selectNodeContents(document.getElementById(b.dataset.copy)); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('done'); }, 1800);
  }));
})();
