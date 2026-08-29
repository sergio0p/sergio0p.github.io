/* PS 02, Part II -- the question sequence for The Fox and the Fallen Grapes.
 *
 * The point of the exercise is that the same two questions get different answers
 * before and after the grapes fall, so the story is metered out rather than
 * shown all at once: the student answers with the fox's boast and nothing else,
 * and only then finds out what she did when the grapes were within reach.
 * Reading the ending first would make the first pair of questions unanswerable
 * in the intended way.
 *
 * One question is live at a time. Choosing an option records it and moves on --
 * the prompt and the selection clear, and the same slot carries the next
 * question. Answered steps stay reachable: they collapse into a record below,
 * and clicking any line reopens it. Nothing is committed until the problem set
 * itself is submitted, so a student who changes their mind at step four can walk
 * back to step one and change it.
 */

const OUT = 'eat grapes';
const IN  = 'don’t eat grapes';

/* The words are words and the operator is maths, and they are set that way: the
 * relata stay in the page's own sans, the relation goes through KaTeX.
 *
 * Not a stylistic choice. Written as bare Unicode, U+227B falls back to whatever
 * font on the reader's machine happens to cover it, and the one it lands on here
 * draws it as a plain angle bracket -- `eat grapes > don't eat grapes`, which is
 * not the relation the course writes and not what the question is asking about.
 * KaTeX ships its own fonts, so every student sees the same succ. */
const PREFERENCES = [
  { id: 'gt', tex: '\\succ', rel: '≻', left: OUT, right: IN },
  { id: 'lt', tex: '\\prec', rel: '≺', left: OUT, right: IN },
  { id: 'eq', tex: '\\sim',  rel: '∼', left: OUT, right: IN },
];

const YES_NO = [
  { id: 'yes', text: 'Yes' },
  { id: 'no',  text: 'No' },
];

/* Before the grapes fall the fox has only talked, so the first pass can ask
 * nothing but what she said. After they fall she has acted, and the question
 * becomes what her choice reveals -- which is the distinction the whole exercise
 * is built to draw. Same three options both times; only the word changes. */
const STATED   = 'What are the <em>stated</em> preferences of the fox?';
const REVEALED = 'What are the <em>revealed</em> preferences of the fox?';
const INFER    = 'Can we infer the fox’s preferences from the data?';

export const STEPS = [
  { id: 'stated-1',   stage: 1, prompt: STATED,   options: PREFERENCES },
  { id: 'infer-1',    stage: 1, prompt: INFER,    options: YES_NO },
  { id: 'revealed-2', stage: 2, prompt: REVEALED, options: PREFERENCES },
  { id: 'infer-2',    stage: 2, prompt: INFER,    options: YES_NO },
];

/* How an answer reads back in the record. The stored id is an encoding and is
 * never shown, the same rule Part I follows. */
export function answerLabel(step, id) {
  const o = step.options.find(x => x.id === id);
  if (!o) return '';
  return o.text ? o.text : `${o.left} ${o.rel} ${o.right}`;
}

function relMarkup(o) {
  if (o.tex && window.katex) {
    try {
      return `<span class="rel">${window.katex.renderToString(o.tex,
        { throwOnError: false })}</span>`;
    } catch (err) { /* fall through to the plain glyph */ }
  }
  return `<span class="rel rel-plain">${o.rel}</span>`;
}

function optionMarkup(o) {
  return o.text
    ? `<span class="opt-text">${o.text}</span>`
    : `<span class="opt-text">${o.left}${relMarkup(o)}${o.right}</span>`;
}

export function createFableQuestions(host, opts) {
  opts = opts || {};
  const onChange = opts.onChange || function () {};
  const onStage = opts.onStage || function () {};   // reveals the story
  const onDone = opts.onDone || function () {};     // reveals the moral
  // Fired only when an answer moves the sequence on, never when the student
  // navigates back: walking back is a deliberate move to somewhere already on
  // screen, and yanking the page would undo it.
  const onAdvance = opts.onAdvance || function () {};
  const answers = {};
  let i = 0;
  let stage = 0;
  let locked = false;      // ignore clicks during the confirm flash

  host.innerHTML =
    '<div class="qcard" id="qcard"></div>' +
    '<ol class="record" id="record"></ol>';
  const card = host.querySelector('#qcard');
  const record = host.querySelector('#record');

  function reveal(upTo) {
    if (upTo <= stage) return;
    stage = upTo;
    onStage(stage);
  }

  function choose(id) {
    if (locked) return;
    const step = STEPS[i];
    answers[step.id] = id;
    onChange(get());

    // Show the choice landing before it clears. Without the beat the card
    // simply swaps and the click reads as if it did nothing.
    locked = true;
    card.querySelectorAll('.opt').forEach(b => {
      b.setAttribute('aria-checked', String(b.dataset.opt === id));
    });
    setTimeout(() => {
      locked = false;
      i += 1;
      draw();
      onAdvance(STEPS[i] || null);
    }, 340);
  }

  function goTo(n) {
    if (locked) return;
    i = Math.max(0, Math.min(STEPS.length, n));
    draw();
  }

  function drawCard() {
    if (i >= STEPS.length) {
      card.className = 'qcard qcard-done';
      card.innerHTML =
        '<p class="done-note">All four answered. Review them below, or change ' +
        'any of them &mdash; nothing is final until you submit the problem set.</p>';
      onDone(true);
      return;
    }
    onDone(false);
    const step = STEPS[i];
    reveal(step.stage);
    card.className = 'qcard';
    card.innerHTML =
      `<p class="qstep">${String(i + 1).padStart(2, '0')} <span>/ ` +
      `${String(STEPS.length).padStart(2, '0')}</span></p>` +
      `<p class="qprompt">${step.prompt}</p>` +
      `<div class="opts" role="radiogroup" aria-label="answer"></div>` +
      (i > 0 ? '<p class="qnav"><button type="button" class="back">' +
               '&larr; previous question</button></p>' : '');

    const opts = card.querySelector('.opts');
    for (const o of step.options) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'opt';
      b.dataset.opt = o.id;
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(answers[step.id] === o.id));
      b.innerHTML = optionMarkup(o);
      b.addEventListener('click', () => choose(o.id));
      opts.appendChild(b);
    }
    const back = card.querySelector('.back');
    if (back) back.addEventListener('click', () => goTo(i - 1));
  }

  function drawRecord() {
    record.innerHTML = '';
    STEPS.forEach((step, n) => {
      if (!(step.id in answers) || n === i) return;
      const li = document.createElement('li');
      li.className = 'record-row';
      const b = document.createElement('button');
      b.type = 'button';
      b.innerHTML =
        `<span class="record-n">${String(n + 1).padStart(2, '0')}</span>` +
        `<span class="record-q">${step.prompt.replace(/<\/?em>/g, '')}</span>` +
        `<span class="record-a">${answerLabel(step, answers[step.id])}</span>`;
      b.addEventListener('click', () => goTo(n));
      li.appendChild(b);
      record.appendChild(li);
    });
  }

  function draw() { drawCard(); drawRecord(); }

  function get() {
    // Stable and comparable, for the payload and the answer key.
    return STEPS.filter(s => s.id in answers).map(s => `${s.id}:${answers[s.id]}`);
  }

  function set(list) {
    for (const k of Object.keys(answers)) delete answers[k];
    for (const s of list || []) {
      const [id, val] = String(s).split(':');
      const step = STEPS.find(x => x.id === id);
      if (step && step.options.some(o => o.id === val)) answers[id] = val;
    }
    i = STEPS.findIndex(s => !(s.id in answers));
    if (i === -1) i = STEPS.length;
    // Re-entering a saved attempt must not hide story the student already read.
    const seen = STEPS.filter(s => s.id in answers).map(s => s.stage);
    reveal(seen.length ? Math.max(...seen) : 1);
    draw();
  }

  function clear() {
    for (const k of Object.keys(answers)) delete answers[k];
    i = 0;
    draw();
    onChange(get());
  }

  draw();
  return { get, set, clear, goTo, element: host, steps: STEPS };
}
