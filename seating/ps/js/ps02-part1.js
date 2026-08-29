/* PS 02, Part I -- three revealed-preference items behind one submission.
 *
 * Each item is its own triangle with its own baskets, and carries two controls:
 * CLEAR wipes the arrows on the item in front of you, SUBMIT files it and moves
 * to the next. The arrows move between items freely, so a student can go back
 * and change I-I after seeing I-III; changing an answer un-files it, because a
 * filed item has to mean "this is what I am handing in", not "this is what I had
 * once". SUBMIT on the last item hands Part I in.
 *
 * Handing in is not final: a group may submit as often as it likes until the due
 * date, and the last submission is the one that is graded. So nothing locks
 * afterwards -- the controls stay live and "submitted" here means "handed in at
 * least once", not "closed".
 *
 * The three versions and the arithmetic behind them are in the Canvas repo at
 * docs/plans/2026-08-28-ps02-part1-progress.md. Income is p·x and is deliberately
 * NOT given to the student -- working it out is the first step of the exercise.
 */
import { createRPTriangle } from './rp-triangle.js';

export const ITEMS = [
  {
    id: 'I-I',
    // a ≽DR b, b ≽DR c, a ≽IR c. Both direct relations are exact equalities, so
    // they are weak, not strict.
    observations: [
      { id: 'a', prices: [2, 3], basket: [6, 1] },
      { id: 'b', prices: [3, 2], basket: [3, 3] },
      { id: 'c', prices: [4, 1], basket: [1, 6] },
    ],
  },
  {
    id: 'I-II',
    // a ≻SDR b, b ≻SDR c, c ≻SDR a -- the cycle violates GARP. In two goods the
    // mutual pair a↔b is unavoidable; the other pairs are unconstrained.
    observations: [
      { id: 'a', prices: [1, 3], basket: [2, 6] },
      { id: 'b', prices: [3, 1], basket: [6, 2] },
      { id: 'c', prices: [7, 1], basket: [2, 11] },
    ],
  },
  {
    id: 'I-III',
    // a ≻SDR b and a ≻SDR c, with nothing at all between b and c.
    observations: [
      { id: 'a', prices: [2, 1], basket: [5, 5] },
      { id: 'b', prices: [3, 2], basket: [1, 6] },
      { id: 'c', prices: [1, 2], basket: [4, 3] },
    ],
  },
];

function button(cls, text, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = cls;
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

export function createPartOne(opts) {
  opts = opts || {};
  const mount = opts.mount;
  const onChange = opts.onChange || function () {};
  const onTitle = opts.onTitle || function () {};
  const onFinal = opts.onFinal || function () {};   // opens the group confirmation
  const onRender = opts.onRender || function () {}; // repaints the item nav

  const widgets = new Array(ITEMS.length).fill(null);
  const submitButtons = new Array(ITEMS.length).fill(null);
  const hosts = [];
  const filed = new Set();
  let i = 0;
  let submitted = false;

  for (const item of ITEMS) {
    const host = document.createElement('div');
    host.className = 'ps-item';
    host.dataset.item = item.id;
    host.hidden = true;
    mount.appendChild(host);
    hosts.push(host);
  }

  // Built on first visit, not up front. A widget created inside a hidden element
  // measures its KaTeX labels against a zero-width box and the baskets come out
  // the wrong size -- a bug that would only show on items I-II and I-III.
  function ensure(n) {
    if (widgets[n]) return widgets[n];
    const w = createRPTriangle(hosts[n], {
      observations: ITEMS[n].observations,
      onChange: () => { if (filed.delete(ITEMS[n].id)) paint(); onChange(get()); },
    });
    w.actions.appendChild(button('rp-clear', 'Clear', () => w.clear()));
    const sub = button('rp-submit', 'Submit', () => submit());
    submitButtons[n] = sub;
    w.actions.appendChild(sub);
    widgets[n] = w;
    return w;
  }

  function show(n) {
    i = Math.max(0, Math.min(ITEMS.length - 1, n));
    ensure(i);
    hosts.forEach((h, k) => { h.hidden = k !== i; });
    onTitle(`PS 02 - Part ${ITEMS[i].id}`);
    paint();
  }

  function submit() {
    filed.add(ITEMS[i].id);
    onChange(get());
    if (i < ITEMS.length - 1) { show(i + 1); return; }
    paint();
    onFinal(get());        // last item: hand off to the group confirmation
  }

  // Handed in. Deliberately does NOT disable anything: resubmission is open
  // until the due date, and a page that greys itself out says the opposite.
  function accept() {
    submitted = true;
    paint();
    onChange(get());
  }

  function paint() {
    const last = i === ITEMS.length - 1;
    const sub = submitButtons[i];
    if (sub) sub.textContent = last ? 'Submit Part I' : 'Submit';
    if (sub) sub.classList.toggle('rp-submit-final', last);
    onRender({
      index: i, id: ITEMS[i].id, filed: [...filed],
      isFiled: filed.has(ITEMS[i].id),
      complete: filed.size === ITEMS.length,
      submitted,
    });
  }

  function get() {
    const answers = {};
    ITEMS.forEach((item, n) => {
      answers[item.id] = widgets[n] ? widgets[n].get() : [];
    });
    return {
      current: ITEMS[i].id,
      answers,
      filed: ITEMS.map(x => x.id).filter(id => filed.has(id)),
      complete: filed.size === ITEMS.length,
      submitted,
    };
  }

  function set(state) {
    state = state || {};
    ITEMS.forEach((item, n) => {
      const a = (state.answers || {})[item.id];
      if (a && a.length) ensure(n).set(a);
    });
    filed.clear();
    for (const id of state.filed || []) filed.add(id);
    show(0);
    onChange(get());
  }

  show(0);

  return {
    show, submit, accept, get, set,
    items: ITEMS,
    widget: n => widgets[n],
    next: () => show(i + 1),
    prev: () => show(i - 1),
    get index() { return i; },
    get isSubmitted() { return submitted; },
  };
}
