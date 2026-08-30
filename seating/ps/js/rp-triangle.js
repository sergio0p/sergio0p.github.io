/* The revealed-preference triangle.
 *
 * Three baskets sit at the vertices of a triangle. The triangle's edges are
 * never drawn -- the vertices are just three well-separated places to put a, b
 * and c, NOT a plot. Nothing here is positioned by the baskets' coordinates and
 * no budget line is shown: the student works the arithmetic on scratch paper and
 * records the conclusion.
 *
 * Interaction: click basket x, click basket y, then click a ranking. That draws
 * one arrow. Clicking an arrow's own ranking again removes it, so work can be
 * redone freely -- nothing is committed until the problem set is submitted.
 *
 * Bending: every arrow uses bend 'left', which bows to the left OF THE
 * DIRECTION OF TRAVEL. So a->b and b->a bow to opposite sides of the same
 * straight line and never overlap, without any per-pair special casing. That
 * matters: version 2 has a mutual pair by construction.
 */
import { render } from '../tikz-svg/dist/tikz-svg.min.js';

/* Three identical arrows -- same weight, same solid line, same head. Colour is
 * the only difference, so the three relations read as one family. */
const ARROW_WIDTH = 2.6;

/* Every widget on the page needs its own marker id namespace. See
 * namespaceMarkers() below for why. */
let instanceCount = 0;

/* Bend, in degrees, and not the library's default 30.
 *
 * tikz-svg departs an edge at (baseAngle - bend) and arrives at
 * (baseAngle + 180 + bend). So at any basket, the arrow arriving from one
 * neighbour and the arrow leaving for the other swing TOWARD each other by
 * 2*bend, while the angle between those two neighbours -- the triangle's
 * interior angle at that vertex -- is at most 60 degrees, since the three of
 * them sum to 180. At bend 30 the gap closes to nothing: a->b was landing at
 * b@331 while b->c left from b@330, so the two read as one line passing
 * straight through the basket instead of one arrow ending and another starting.
 *
 * Two gaps compete for the same budget at each vertex:
 *     across neighbours   interior - 2*bend   (arrival vs the next departure)
 *     within a pair       2*bend              (a->b vs b->a, which must not merge)
 * They are equal at bend = interior/4. This triangle's tightest interior angle
 * is 59.04 degrees, so 15 splits it almost exactly evenly and leaves both gaps
 * near 30 degrees. test_rp_triangle.py measures all twelve attachments and
 * fails if any two at one basket come within 20 degrees. */
const BEND = 15;

export const RANKINGS = [
  { key: 'SDR', label: 'strictly directly revealed', sym: '\\underset{\\mathrm{SDR}}{\\succ}',
    color: '#dc322f' },
  { key: 'DR',  label: 'directly revealed',          sym: '\\underset{\\mathrm{DR}}{\\succeq}',
    color: '#268bd2' },
  { key: 'IR',  label: 'indirectly revealed',        sym: '\\underset{\\mathrm{IR}}{\\succeq}',
    color: '#00a651' },
];

const VERTICES = {
  a: { x: 0.50, y: 0.06 },   // top
  b: { x: 0.10, y: 0.86 },   // bottom left
  c: { x: 0.90, y: 0.86 },   // bottom right
};

const SIZE = { w: 360, h: 300 };

/* The baskets. `radius` is the library's actual size property -- `minWidth` and
 * `minHeight`, which this used to pass, appear nowhere in tikz-svg and were
 * silently ignored, so the circles had been sitting at DEFAULTS.nodeRadius (20,
 * drawn as 17 once outerSep is taken off) the whole time. 24 is that default
 * plus the 20% asked for; the viewBox is untouched, so the baskets grow into the
 * gaps rather than the figure growing on the page.
 *
 * Warm dark grey discs with white letters, so a basket reads as an object rather
 * than an outline -- lifted well off the course palette's #2b211b soot, which as
 * a fill was reading as flat black.
 *
 * Selecting one inverts it: cream ground, dark letter. That is the black-figure
 * to red-figure flip the course site's own palette is taken from, and it is a
 * far louder signal than a colour change at the same lightness -- which matters,
 * because the selected basket is the one the student most needs to pick out. */
const BASKET = {
  radius: 24,
  fill:      '#4a3d35',  fillOn:      '#e6d1ad',
  stroke:    '#2b211b',  strokeOn:    '#71311f',
  labelColor:'#ffffff',  labelColorOn:'#171310',
  shadow: { dx: 0, dy: 2, blur: 4, color: 'rgba(23,19,16,0.34)' },
};

/* What the student reads. The stored form (`a>b:DR`) is an encoding, not
 * notation -- it must never reach the screen. */
export function relationTeX(entry) {
  const r = RANKINGS.find(function (x) { return x.key === entry.rel; });
  return entry.from + ' ' + (r ? r.sym : '\\sim') + ' ' + entry.to;
}

function tex(src) {
  if (window.katex) {
    try { return window.katex.renderToString(src, { throwOnError: false }); }
    catch (err) { /* fall through to plain text */ }
  }
  return src;
}

/* "When prices were p_X = 2 and p_Y = 3, basket a = (6, 1) was chosen."
 *
 * Prose rather than a table on purpose: each line is one shopping trip, and the
 * pairing of a price vector with the basket bought AT those prices is the whole
 * content of the exercise. A table invites reading down a column, which is the
 * one direction that means nothing here. */
function renderObservations(host, observations) {
  host.innerHTML = '';
  for (const o of observations) {
    const li = document.createElement('li');
    li.innerHTML =
      'When prices were ' + tex('p_X = ' + o.prices[0]) +
      ' and ' + tex('p_Y = ' + o.prices[1]) + ', basket ' +
      tex(o.id + ' = (' + o.basket[0] + ',\\, ' + o.basket[1] + ')') +
      ' was chosen.';
    host.appendChild(li);
  }
}

function railLabel(text) {
  const h = document.createElement('p');
  h.className = 'rp-rail-label';
  h.textContent = text;
  return h;
}

export function createRPTriangle(host, opts) {
  opts = opts || {};
  const ids = opts.baskets || ['a', 'b', 'c'];
  const onChange = opts.onChange || function () {};
  const uid = 'rp' + (++instanceCount);   // this widget's marker id namespace

  // answers: array of { from, to, rel }, at most one per ordered pair
  let answers = [];
  let pick = [];               // 0, 1 or 2 baskets currently selected

  host.classList.add('rp-block');
  host.innerHTML = '';

  const row = document.createElement('div');
  row.className = 'rp-widget';
  host.appendChild(row);

  // The figure comes first in the DOM as well as first on screen. It is the
  // thing being worked on; everything else on the page is consulted, not read.
  const stage = document.createElement('div');
  stage.className = 'rp-stage';
  const ground = document.createElement('div');
  ground.className = 'rp-stage-ground';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${SIZE.w} ${SIZE.h}`);
  svg.classList.add('rp-svg');
  ground.appendChild(svg);
  stage.appendChild(ground);
  const prompt = document.createElement('p');
  prompt.className = 'rp-prompt';
  stage.appendChild(prompt);
  row.appendChild(stage);

  // The rail: what has to stay within reach while the student works, held
  // narrow and unboxed so it never competes with the figure.
  const rail = document.createElement('div');
  rail.className = 'rp-rail';
  row.appendChild(rail);

  // The observations. Without these the question cannot be answered at all:
  // the triangle is schematic, so nothing on the figure says what was bought
  // or at what prices.
  rail.appendChild(railLabel('Data'));
  const data = document.createElement('ul');
  data.className = 'rp-data';
  rail.appendChild(data);
  renderObservations(data, opts.observations || []);

  // Built as a legend, not a toolbar: the marks here are the same three arrows
  // that get drawn on the figure, in the same colours.
  rail.appendChild(railLabel('Rankings'));
  const palette = document.createElement('div');
  palette.className = 'rp-palette';
  rail.appendChild(palette);

  // Spans both columns, under everything: the drawing restated in words, with a
  // slot at the far end for controls. The sentence and the control that wipes it
  // belong on one line -- stacked, the button reads as the start of a new
  // section rather than as an action on the sentence above it.
  const summaryRow = document.createElement('div');
  summaryRow.className = 'rp-summary-row';
  const summary = document.createElement('p');
  summary.className = 'rp-summary';
  summaryRow.appendChild(summary);
  const actions = document.createElement('div');
  actions.className = 'rp-actions';
  summaryRow.appendChild(actions);
  row.appendChild(summaryRow);

  RANKINGS.forEach(function (r) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'rp-rank';
    b.dataset.rel = r.key;
    b.disabled = true;
    b.innerHTML =
      '<svg viewBox="0 0 54 16" aria-hidden="true">' +
      '<line x1="2" y1="8" x2="42" y2="8" stroke="' + r.color +
      '" stroke-width="' + ARROW_WIDTH + '"/>' +
      '<path d="M42 3 L52 8 L42 13 Z" fill="' + r.color + '"/></svg>' +
      '<span class="rp-rank-key">' + r.key + '</span>' +
      '<span class="rp-rank-label">' + r.label + '</span>';
    b.addEventListener('click', function () { choose(r.key); });
    palette.appendChild(b);
  });

  function px(id) {
    const v = VERTICES[id];
    return { x: v.x * SIZE.w, y: v.y * SIZE.h };
  }

  function existing(from, to) {
    return answers.find(function (e) { return e.from === from && e.to === to; });
  }

  function choose(rel) {
    if (pick.length !== 2) return;
    const [from, to] = pick;
    const had = existing(from, to);
    if (had && had.rel === rel) {
      answers = answers.filter(function (e) { return e !== had; });   // toggle off
    } else if (had) {
      had.rel = rel;                                                  // replace
    } else {
      answers.push({ from: from, to: to, rel: rel });
    }
    pick = [];
    draw();
    onChange(get());
  }

  function tap(id) {
    if (pick.length === 2) pick = [];
    if (pick[0] === id) { pick = []; }
    else if (pick.length === 0) { pick = [id]; }
    else { pick = [pick[0], id]; }
    draw();
  }

  function say() {
    if (pick.length === 0) {
      prompt.textContent = 'Click a basket, then a second basket, then a ranking.';
    } else if (pick.length === 1) {
      prompt.innerHTML = 'First basket <strong>' + pick[0] +
        '</strong>. Now click the second basket.';
    } else {
      const had = existing(pick[0], pick[1]);
      prompt.innerHTML = 'Ranking of <strong>' + pick[0] + '</strong> against <strong>' +
        pick[1] + '</strong>?' +
        (had ? ' Currently <strong>' + had.rel + '</strong> — click it again to clear.' : '');
    }
    palette.querySelectorAll('.rp-rank').forEach(function (b) {
      b.disabled = pick.length !== 2;
      const had = pick.length === 2 && existing(pick[0], pick[1]);
      b.classList.toggle('rp-rank-on', !!had && had.rel === b.dataset.rel);
    });
  }

  function draw() {
    const drawList = [];

    for (const e of answers) {
      const r = RANKINGS.find(function (x) { return x.key === e.rel; });
      drawList.push({
        type: 'edge', from: e.from, to: e.to, bend: BEND,
        stroke: r.color, strokeWidth: ARROW_WIDTH, arrow: '->', arrowSize: 9,
      });
    }

    for (const id of ids) {
      const p = px(id);
      const on = pick.includes(id);
      drawList.push({
        type: 'node', id: id, position: p, label: '$' + id + '$',
        shape: 'circle', radius: BASKET.radius,
        fill: on ? BASKET.fillOn : BASKET.fill,
        stroke: on ? BASKET.strokeOn : BASKET.stroke,
        strokeWidth: on ? 2.5 : 1.4,
        labelColor: on ? BASKET.labelColorOn : BASKET.labelColor,
        shadow: BASKET.shadow,
      });
    }

    render(svg, { scale: 1, originX: 0, originY: 0, draw: drawList });
    namespaceMarkers();          // before the first paint, not after it

    // render() rebuilds the node <g> elements again, asynchronously, once KaTeX
    // has laid the labels out -- so anything attached to the elements it returns
    // is thrown away before the first paint. Handlers therefore live on the svg
    // (see below, attached once) and only the decoration is re-applied, twice:
    // now, and after the frame in which that second pass lands.
    decorate();
    say();
    renderSummary();
  }

  /* The drawn basket is 48 units across, which lands at ~34 CSS px on a phone --
   * under every touch-target minimum there is, on a page whose entire
   * interaction is tapping baskets. Rather than draw them bigger, each node gets
   * an invisible circle roughly half again the radius. pointer-events="all" is
   * required: a fill of "none" or "transparent" is not painted, so the default
   * visiblePainted would ignore it. */
  const HIT_RADIUS = 36;

  /* Give this widget's arrowheads ids nobody else on the page can claim.
   *
   * tikz-svg names a marker after what it looks like -- `arrow-stealth-9-268bd2`
   * is "stealth tip, size 9, in blue" -- so two diagrams that use the same
   * arrow in the same colour emit the same id. Part I keeps all three items in
   * one document and hides the ones you are not on, and `url(#id)` takes the
   * FIRST match in the document: on item I-II every blue and green arrowhead was
   * resolving to item I-I's marker, sitting inside a `hidden` div. Chrome and
   * Firefox will not paint a marker out of a display:none subtree, so the heads
   * silently disappeared while the shortened line stayed -- and the head that
   * happened to be a colour the earlier item had not used still worked, which is
   * what made it look random. (Safari paints them, which is why it was the one
   * browser without this bug and the only one with the label bug.)
   *
   * Idempotent, and it re-checks the references rather than trusting the rename:
   * render() rebuilds this subtree on its own schedule once KaTeX has measured
   * the labels, so this runs again from the MutationObserver below and has to
   * cope with defs and paths being replaced independently. */
  function namespaceMarkers() {
    for (const m of svg.querySelectorAll('defs marker')) {
      if (m.id && !m.id.startsWith(uid + '-')) m.id = uid + '-' + m.id;
    }
    for (const el of svg.querySelectorAll('[marker-end], [marker-start]')) {
      for (const attr of ['marker-end', 'marker-start']) {
        const ref = /^url\(#(.+)\)$/.exec(el.getAttribute(attr) || '');
        if (!ref || ref[1].startsWith(uid + '-')) continue;
        // Only if this widget really owns a marker by that name -- a reference
        // we cannot satisfy locally is better left pointing where it did.
        if (svg.querySelector('marker[id="' + uid + '-' + ref[1] + '"]')) {
          el.setAttribute(attr, 'url(#' + uid + '-' + ref[1] + ')');
        }
      }
    }
  }

  function decorate() {
    for (const id of ids) {
      const g = svg.querySelector('g.node#node-' + id);
      if (!g) continue;
      g.style.cursor = 'pointer';
      g.setAttribute('tabindex', '0');
      g.setAttribute('role', 'button');
      g.setAttribute('aria-label', 'basket ' + id);

      if (!g.querySelector('.rp-hit')) {
        const drawn = g.querySelector('circle:not(.rp-hit)');
        if (!drawn) continue;
        const hit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        hit.setAttribute('class', 'rp-hit');
        hit.setAttribute('cx', drawn.getAttribute('cx') || 0);
        hit.setAttribute('cy', drawn.getAttribute('cy') || 0);
        hit.setAttribute('r', HIT_RADIUS);
        hit.setAttribute('fill', 'none');
        hit.setAttribute('pointer-events', 'all');
        g.insertBefore(hit, g.firstChild);
      }
    }
  }

  function basketAt(target) {
    const g = target && target.closest && target.closest('g.node');
    if (!g || !g.id) return null;
    const id = g.id.replace(/^node-/, '');
    return ids.includes(id) ? id : null;
  }

  /* Read as a sentence, not a row of tiles. Two relations set side by side with
   * only whitespace between them read as one four-symbol expression -- commas
   * and a final "and" are what separate the claims. */
  function renderSummary() {
    summary.innerHTML = '';
    if (!answers.length) {
      summary.className = 'rp-summary rp-summary-empty';
      summary.textContent = 'No rankings recorded yet.';
      return;
    }
    summary.className = 'rp-summary';

    const order = { SDR: 0, DR: 1, IR: 2 };
    const sorted = answers.slice().sort(function (x, y) {
      return (order[x.rel] - order[y.rel]) ||
             (x.from + x.to).localeCompare(y.from + y.to);
    });

    sorted.forEach(function (e, i) {
      if (i > 0) {
        summary.appendChild(document.createTextNode(
          i === sorted.length - 1 ? ' and ' : ', '));
      }
      const r = RANKINGS.find(function (x) { return x.key === e.rel; });
      const span = document.createElement('span');
      span.className = 'rp-rel';
      span.style.color = r ? r.color : 'inherit';
      const tex = relationTeX(e);
      if (window.katex) {
        try {
          span.innerHTML = window.katex.renderToString(tex, { throwOnError: false });
        } catch (err) { span.textContent = tex; }
      } else {
        span.textContent = tex;
      }
      summary.appendChild(span);
    });
    summary.appendChild(document.createTextNode('.'));
  }

  function get() {
    // A stable, comparable shape for the payload and the answer key.
    return answers
      .map(function (e) { return e.from + '>' + e.to + ':' + e.rel; })
      .sort();
  }

  function set(list) {
    answers = (list || []).map(function (s) {
      const [pair, rel] = String(s).split(':');
      const [from, to] = pair.split('>');
      return { from: from, to: to, rel: rel };
    }).filter(function (e) {
      return VERTICES[e.from] && VERTICES[e.to] &&
             RANKINGS.some(function (r) { return r.key === e.rel; });
    });
    pick = [];
    draw();
  }

  function clear() { answers = []; pick = []; draw(); onChange(get()); }

  // The async label pass replaces the node <g> elements at a time nothing here
  // controls, so re-decorating on a timer would be a race. Watch the subtree
  // instead and re-apply whenever children are swapped. childList only --
  // observing attributes would retrigger on our own writes.
  new MutationObserver(function () { namespaceMarkers(); decorate(); })
    .observe(svg, { childList: true, subtree: true });

  svg.addEventListener('click', function (ev) {
    const id = basketAt(ev.target);
    if (id) tap(id);
  });
  svg.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const id = basketAt(ev.target);
    if (id) { ev.preventDefault(); tap(id); }
  });

  draw();
  return { get: get, set: set, clear: clear, element: host, actions: actions };
}
