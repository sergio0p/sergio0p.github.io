/* ECON 416 seating — the whole game, one file, no build step.
 *
 * The room is a single background image emitted by `tools/room_kit.py --emit`;
 * everything else (Link, the Moblin, the dialog, the text) is drawn on top of
 * it every frame.  There is no tile bookkeeping: repaint the background and the
 * two sprites and the screen is correct by construction.
 *
 * Geometry comes from `data/room-layout.json` through the SAME formula
 * `place_seats()` paints with, so the renderer and the Python tools cannot
 * disagree about where a seat is:
 *
 *     x = WALL + (PAD_LEFT + col - c0) * T
 *     y = WALL + (PAD_TOP  + row - r0) * T
 *
 * Claiming is stubbed behind `claimSeat()` — one async function, so Phase 2's
 * Firestore transaction drops in where localStorage is today without touching
 * anything else.  To clear a claim while testing: `seating.reset()` in the
 * console.
 */
(() => {
'use strict';

// --- geometry (must match tools/room_kit.py) ---------------------------------
const T = 16, WALL = 32, PAD_TOP = 2, PAD_LEFT = 1;

// --- feel --------------------------------------------------------------------
const MS_PER_TILE = 150;        // Link, one tile
const MOBLIN_MS_PER_TILE = 300; // the professor paces at half speed
const STEP_FRAME_PX = 8;        // sprite frames alternate every half tile
// The NES death: every enemy vanishes, the palette flips to red, Link spins in
// place, then he disappears and the screen fades to black under the GAME OVER
// menu.  FLARE_MS is the white pop on the hit itself; the red is not a strobe —
// on the console it is a palette change that simply stays.
const SPIN_MS = 70, DEATH_MS = 1120, FLARE_MS = 140, FADE_MS = 420;
const SWIPE_PX = 24;            // CSS px before a drag counts as a swipe
// Picking Link up: how much slack there is around the sprite (art px), and how
// far the finger has to travel (CSS px) before a touch on him stops being a tap.
const GRAB_PAD = 8, DRAG_PX = 6;
// Steering yourself onto a seat is not the same as asking to go there: crossing
// a row costs 150ms a tile, so a seat you walked over must not grab you.  Stand
// still on one this long and the question comes anyway.
const DWELL_MS = 1600;
const CLAIM_KEY = 'econ416-seat';

// --- the font atlas ----------------------------------------------------------
// Emitted by `tools/nes_text.py --atlas`: 44 glyphs, 16 per row, 8px cells, so
// the cell for a character is just its index in this string.  The NES font has
// no lowercase, colon or slash — every string below is caps within this set.
const CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ,!'&.\"?-";
const GLYPH = 8, ATLAS_COLS = 16;

const ART = {
  room: 'assets/room.png',
  font: 'assets/font-white.png',
  linkDown1: 'assets/tiles/link-down-1.png',
  linkDown2: 'assets/tiles/link-down-2.png',
  linkRight1: 'assets/tiles/link-right-1.png',
  linkRight2: 'assets/tiles/link-right-2.png',
  linkUp1: 'assets/tiles/link-up-1.png',
  linkUp2: 'assets/tiles/link-up-2.png',
  moblinDown: 'assets/tiles/moblin-down.png',
  moblinUp: 'assets/tiles/moblin-up.png',
  moblinRight1: 'assets/tiles/moblin-right-1.png',
  moblinRight2: 'assets/tiles/moblin-right-2.png',
};

// Neither sheet has a left-facing side pose — both were ripped facing right.
// The game itself drew the other way by mirroring, and so do we
// (ctx.scale(-1, 1)), which is why both these tables name only one side.
const LINK_FRAMES = {
  down: ['linkDown1', 'linkDown2'],
  left: ['linkRight1', 'linkRight2'],
  up: ['linkUp1', 'linkUp2'],
  right: ['linkRight1', 'linkRight2'],
};
const MOBLIN_FRAMES = ['moblinRight1', 'moblinRight2'];
const SPIN = ['down', 'left', 'up', 'right'];   // the NES death spin, in order

const art = {};
const stage = document.getElementById('stage');
const canvas = document.getElementById('room');
const ctx = canvas.getContext('2d');
const hintCanvas = document.getElementById('hint');
const hintCtx = hintCanvas.getContext('2d');

let layout, seatsByCell, seatsById, ICOLS, IROWS, R0, C0;
let ENTRANCE, MOBLIN_ROW = 0, MOBLIN_START = 0;

const game = {
  state: 'IDLE',                // IDLE WALKING DRAGGING DIALOG SEATED DYING GAMEOVER
  link: { x: 0, y: 0, facing: 'down', walked: 0, path: [] },
  moblin: { x: 0, y: 0, dir: 1, walked: 0, dead: false },
  dialog: null,
  deathT: 0,
  steered: false,               // did the player drive the last step themselves?
  pending: null,                // { seat, t } — a seat waiting out its dwell
};

// --- loading -----------------------------------------------------------------

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`cannot load ${src}`));
    img.src = src;
  });
}

async function boot() {
  const [json] = await Promise.all([
    fetch('data/room-layout.json').then(r => r.json()),
    ...Object.entries(ART).map(([key, src]) =>
      loadImage(src).then(img => { art[key] = img; })),
  ]);
  setup(json);
  requestAnimationFrame(frame);
}

function setup(json) {
  layout = json;
  const [r0, r1] = layout.grid.seat_rows, [c0, c1] = layout.grid.seat_cols;
  R0 = r0; C0 = c0;
  ICOLS = PAD_LEFT + (c1 - c0 + 1);
  IROWS = PAD_TOP + (r1 - r0 + 1);
  canvas.width = WALL * 2 + ICOLS * T;
  canvas.height = WALL * 2 + IROWS * T;
  hintCanvas.width = canvas.width;
  // The frame takes its shape from the room, not from a number in the stylesheet.
  stage.style.aspectRatio = `${canvas.width} / ${canvas.height}`;
  applyView();
  ctx.imageSmoothingEnabled = false;
  hintCtx.imageSmoothingEnabled = false;

  seatsByCell = new Map();
  seatsById = new Map();
  for (const seat of layout.seats) {
    const cell = seatCell(seat);
    seatsByCell.set(cellKey(cell.ic, cell.ir), seat);
    seatsById.set(seat.id, seat);
  }

  // The front door is drawn in the left wall across interior rows 0-1
  // (room_kit's doors=[("left", 0)]).  Link steps in on the lower of the two,
  // which is also one row clear of the Moblin's lane.
  ENTRANCE = { ic: 0, ir: 1 };

  // room-layout.json puts the instructor at seat cell (0, 7) and says the
  // renderer may nudge it toward the board.  Interior row 0 is that nudge: the
  // band right under the board, where a professor actually paces — and the one
  // row no route to a seat ever needs, so autopilot never walks into him.
  const instructor = layout.features.find(f => f.type === 'monster');
  MOBLIN_START = instructor ? PAD_LEFT + instructor.cell.col - C0 : 0;
  spawnMoblin();

  placeLink(ENTRANCE);
  restoreClaim();
  // TAP or CLICK — and it re-draws if the device changes its mind (a tablet
  // gaining a mouse, or devtools switching to responsive mode).
  COARSE.addEventListener('change', drawHint);
  drawHint();
}

// --- cells and pixels --------------------------------------------------------

const cellKey = (ic, ir) => `${ic},${ir}`;
const seatCell = seat => ({ ic: PAD_LEFT + seat.col - C0, ir: PAD_TOP + seat.row - R0 });
const cellX = ic => WALL + ic * T;
const cellY = ir => WALL + ir * T;
const inRoom = (ic, ir) => ic >= 0 && ic < ICOLS && ir >= 0 && ir < IROWS;
const seatAt = (ic, ir) => seatsByCell.get(cellKey(ic, ir));
const isOpen = seat => !!seat && seat.usable && !seat.reserved;

function linkCell() {
  return { ic: Math.round((game.link.x - WALL) / T), ir: Math.round((game.link.y - WALL) / T) };
}

function placeLink(cell, facing = 'down') {
  game.link.x = cellX(cell.ic);
  game.link.y = cellY(cell.ir);
  game.link.facing = facing;
  game.link.path.length = 0;
  game.pending = null;          // teleporting cancels any seat waiting to ask
}

// Back to his mark, pacing right — at the start of the game and after a retry.
function spawnMoblin() {
  const m = game.moblin;
  m.x = cellX(MOBLIN_START);
  m.y = cellY(MOBLIN_ROW);
  m.dir = 1;
  m.walked = 0;
  m.dead = false;
}

/* Shortest route over the interior, avoiding the Moblin's lane when it can.
 * Walls are simply not interior cells, so there is nothing else to exclude:
 * a lecture hall is walkable everywhere, seats included. */
function findPath(from, to) {
  for (const avoidLane of [true, false]) {
    const path = bfs(from, to, avoidLane);
    if (path) return path;
  }
  return null;
}

function bfs(from, to, avoidLane) {
  const blocked = (ic, ir) =>
    avoidLane && ir === MOBLIN_ROW && !(ic === from.ic && ir === from.ir);
  const start = cellKey(from.ic, from.ir), goal = cellKey(to.ic, to.ir);
  const came = new Map([[start, null]]);
  const queue = [from];
  for (let head = 0; head < queue.length; head++) {
    const { ic, ir } = queue[head];
    if (cellKey(ic, ir) === goal) {
      const path = [];
      for (let at = goal; came.get(at); at = came.get(at)) {
        const [c, r] = at.split(',').map(Number);
        path.unshift({ ic: c, ir: r });
      }
      return path;
    }
    for (const [dc, dr] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
      const nc = ic + dc, nr = ir + dr, key = cellKey(nc, nr);
      if (!inRoom(nc, nr) || came.has(key) || blocked(nc, nr)) continue;
      came.set(key, cellKey(ic, ir));
      queue.push({ ic: nc, ir: nr });
    }
  }
  return null;
}

// --- text --------------------------------------------------------------------

/* Draw a string from the atlas.  Out-of-charset characters are dropped with a
 * warning rather than silently: `nes_text.py` raises on them at build time, and
 * a hole in a dialog should be just as loud here. */
function drawText(target, text, x, y) {
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === ' ') continue;
    const at = CHARSET.indexOf(ch);
    if (at < 0) { console.warn(`not in the NES charset: ${ch}`); continue; }
    target.drawImage(art.font,
      (at % ATLAS_COLS) * GLYPH, Math.floor(at / ATLAS_COLS) * GLYPH, GLYPH, GLYPH,
      x + i * GLYPH, y, GLYPH, GLYPH);
  }
}

const textWidth = text => text.length * GLYPH;

const COARSE = matchMedia('(pointer: coarse)');

function drawHint() {
  // Nothing to tap while you are dying or dead, so the line goes quiet.
  const text = game.state === 'SEATED' ? 'SEAT CLAIMED'
    : game.state === 'DYING' || game.state === 'GAMEOVER' ? ''
    : COARSE.matches ? 'TAP A SEAT' : 'CLICK A SEAT';
  hintCtx.clearRect(0, 0, hintCanvas.width, hintCanvas.height);
  drawText(hintCtx, text, (hintCanvas.width - textWidth(text)) >> 1, 4);
}

// --- the loop ----------------------------------------------------------------

let lastFrame = 0;

function frame(now) {
  const dt = lastFrame ? Math.min(now - lastFrame, 100) : 0;
  lastFrame = now;
  update(dt);
  draw();
  requestAnimationFrame(frame);
}

function update(dt) {
  if (!game.dialog) moveMoblin(dt);
  if (game.state === 'WALKING') moveLink(dt);
  if (game.state === 'IDLE') tickDwell(dt);
  if (game.state === 'DYING') tickDeath(dt);
  // Dragged into the professor counts: he is not safe to touch just because you
  // are the one moving.
  if (game.state === 'IDLE' || game.state === 'WALKING' || game.state === 'DRAGGING') {
    checkCollision();
  }
}

/* The spin, then the fade.  Link twirls through the four facings for DEATH_MS;
 * after that he is gone (`linkVisible`) and the room dissolves to black, which
 * is what the GAME OVER menu opens on. */
function tickDeath(dt) {
  game.deathT += dt;
  if (game.deathT < DEATH_MS) {
    game.link.facing = SPIN[Math.floor(game.deathT / SPIN_MS) % SPIN.length];
  } else if (game.deathT >= DEATH_MS + FADE_MS) {
    openGameOver();
  }
}

function moveLink(dt) {
  const link = game.link;
  const step = link.path[0];
  if (!step) { game.state = 'IDLE'; return; }

  const tx = cellX(step.ic), ty = cellY(step.ir);
  const dx = tx - link.x, dy = ty - link.y;
  link.facing = dx > 0 ? 'right' : dx < 0 ? 'left' : dy > 0 ? 'down' : 'up';

  const remaining = Math.abs(dx) + Math.abs(dy);
  const travel = (T / MS_PER_TILE) * dt;
  link.walked += Math.min(travel, remaining);
  if (travel >= remaining) {
    link.x = tx; link.y = ty;
    link.path.shift();
    if (!link.path.length) arrive(step);
  } else {
    link.x += Math.sign(dx) * Math.min(travel, Math.abs(dx));
    link.y += Math.sign(dy) * Math.min(travel, Math.abs(dy));
  }
}

/* End of the route.  Arriving by tap is a request — the seat was the whole point
 * of the walk, so ask at once.  Arriving by arrow or swipe is just where the
 * player happens to be standing, so start the dwell instead and let another step
 * cancel it. */
function arrive(cell) {
  game.state = 'IDLE';
  const seat = seatAt(cell.ic, cell.ir);
  if (!isOpen(seat)) return;
  if (game.steered) game.pending = { seat, t: 0 };
  else openDialog(seat);
}

function tickDwell(dt) {
  if (!game.pending) return;
  game.pending.t += dt;
  if (game.pending.t >= DWELL_MS) openDialog(game.pending.seat);
}

function moveMoblin(dt) {
  const m = game.moblin;
  if (m.dead) return;
  const travel = (T / MOBLIN_MS_PER_TILE) * dt;
  m.x += m.dir * travel;
  m.walked += travel;
  const left = cellX(0), right = cellX(ICOLS - 1);
  if (m.x <= left) { m.x = left; m.dir = 1; }
  if (m.x >= right) { m.x = right; m.dir = -1; }
}

/* Touching the professor is fatal.  Sharing a cell is the obvious case; the
 * 8px test catches the mid-step overlaps, which is most of them. */
function checkCollision() {
  const overlap = (a, b) => Math.min(a + T, b + T) - Math.max(a, b);
  if (overlap(game.link.x, game.moblin.x) >= 8 &&
      overlap(game.link.y, game.moblin.y) >= 8) {
    game.state = 'DYING';
    game.deathT = 0;
    game.link.path.length = 0;
    game.pending = null;
    grab = null;                // whatever the finger was doing, it is over
    game.moblin.dead = true;    // the NES clears the screen of enemies first
    drawHint();
  }
}

// --- drawing -----------------------------------------------------------------

function draw() {
  ctx.drawImage(art.room, 0, 0);
  drawMoblin();
  if (linkVisible()) drawLink();
  if (game.state === 'DYING') drawDeath();
  if (game.state === 'GAMEOVER') wash('#000', 1);
  if (game.dialog) drawDialog();
}

// He spins for DEATH_MS and is gone from there on — the fade happens on an
// empty room, and GAME OVER opens on black.
const linkVisible = () => game.state !== 'GAMEOVER' &&
  !(game.state === 'DYING' && game.deathT >= DEATH_MS);

function wash(color, alpha, blend) {
  if (alpha <= 0) return;
  ctx.save();
  if (blend) ctx.globalCompositeOperation = blend;
  ctx.globalAlpha = Math.min(alpha, 1);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.restore();
}

/* The palette change.  `color` blending takes the hue from the fill and keeps
 * the room's own luminance, which is what an NES palette swap looks like — the
 * blues go red and the black stays black.  It appears at once and holds: on the
 * console this is one flip, not a strobe. */
function drawDeath() {
  const t = game.deathT;
  wash('#db2b00', 1, 'color');
  if (t < FLARE_MS) wash('#fff', 0.75 * (1 - t / FLARE_MS));
  if (t >= DEATH_MS) wash('#000', (t - DEATH_MS) / FADE_MS);
}

function drawSprite(img, x, y, mirrored) {
  x = Math.round(x); y = Math.round(y);
  if (!mirrored) { ctx.drawImage(img, x, y); return; }
  ctx.save();
  ctx.translate(x + T, y);
  ctx.scale(-1, 1);
  ctx.drawImage(img, 0, 0);
  ctx.restore();
}

function drawLink() {
  const link = game.link;
  const moving = game.state === 'WALKING' || game.state === 'DRAGGING';
  const step = moving ? Math.floor(link.walked / STEP_FRAME_PX) % 2 : 0;
  const img = art[LINK_FRAMES[link.facing][step]];
  drawSprite(img, link.x, link.y, link.facing === 'left');
}

function drawMoblin() {
  const m = game.moblin;
  if (m.dead) return;
  const step = Math.floor(m.walked / STEP_FRAME_PX) % 2;
  drawSprite(art[MOBLIN_FRAMES[step]], m.x, m.y, m.dir < 0);
}

/* A canvas-drawn NES message box: black fill, white double border, atlas text.
 * No new art, and it sizes itself to whatever the seat's line comes out as. */
const DIALOG = { padX: 12, padY: 10, gap: 24, cursorW: 6, rows: [0, 12, 28] };

function dialogBox() {
  const { title, prompt, options } = game.dialog;
  const optionsW = options.reduce(
    (w, o) => w + DIALOG.cursorW + textWidth(o.label), 0) + DIALOG.gap;
  const inner = Math.max(textWidth(title), textWidth(prompt), optionsW);
  const w = inner + DIALOG.padX * 2, h = DIALOG.rows[2] + GLYPH + DIALOG.padY * 2;
  // A seat box goes in the half Link is not standing in: the whole point is to
  // confirm THIS seat, so the seat has to stay visible while you answer.  GAME
  // OVER has an empty black room to itself, so it takes the middle.
  const y = game.dialog.kind === 'GAMEOVER' ? (canvas.height - h) >> 1
    : game.link.y > canvas.height / 2 ? WALL + T
    : canvas.height - WALL - T - h;
  return { x: (canvas.width - w) >> 1, y, w, h, inner, optionsW };
}

function outline(x, y, w, h) {
  ctx.fillRect(x, y, w, 1);
  ctx.fillRect(x, y + h - 1, w, 1);
  ctx.fillRect(x, y, 1, h);
  ctx.fillRect(x + w - 1, y, 1, h);
}

function drawDialog() {
  const box = dialogBox();
  ctx.fillStyle = '#000';
  ctx.fillRect(box.x, box.y, box.w, box.h);
  ctx.fillStyle = '#fff';
  outline(box.x, box.y, box.w, box.h);
  outline(box.x + 2, box.y + 2, box.w - 4, box.h - 4);

  const cx = box.x + (box.w >> 1);
  const line = (text, row) =>
    drawText(ctx, text, cx - (textWidth(text) >> 1), box.y + DIALOG.padY + DIALOG.rows[row]);
  line(game.dialog.title, 0);
  line(game.dialog.prompt, 1);

  let x = cx - (box.optionsW >> 1);
  const y = box.y + DIALOG.padY + DIALOG.rows[2];
  for (const option of game.dialog.options) {
    if (option.label === game.dialog.choice) drawCursor(x, y);
    x += DIALOG.cursorW;
    drawText(ctx, option.label, x, y);
    option.hit = { x: x - DIALOG.cursorW, y: y - 4, w: textWidth(option.label) + DIALOG.cursorW + 4, h: GLYPH + 8 };
    x += textWidth(option.label) + DIALOG.gap;
  }
}

// The charset has no arrow, so the cursor is four columns of pixels.
function drawCursor(x, y) {
  for (let i = 0; i < 4; i++) ctx.fillRect(x + i, y + i, 1, 7 - 2 * i);
}

// --- the dialog --------------------------------------------------------------

function openDialog(seat) {
  game.state = 'DIALOG';
  game.pending = null;
  suspendZoom();
  game.link.path.length = 0;
  game.link.facing = 'down';
  game.dialog = {
    kind: 'SEAT',
    seat,
    // The layout's own coordinates: rows from the board, columns from the
    // instructor's right.  No colon in the charset, so words and digits it is.
    title: `ROW ${seat.row} SEAT ${seat.col}`,
    prompt: 'SIT HERE?',
    choice: 'YES',
    options: [{ label: 'YES' }, { label: 'NO' }],
  };
}

function openGameOver() {
  game.state = 'GAMEOVER';
  suspendZoom();
  game.dialog = {
    kind: 'GAMEOVER',
    title: 'GAME OVER',
    prompt: 'RETRY?',
    choice: 'YES',
    options: [{ label: 'YES' }, { label: 'NO' }],
  };
}

async function answerDialog(choice) {
  if (game.dialog.kind === 'GAMEOVER') {
    // NO is not a way out — there is nothing behind this screen but the room
    // you just died in, so the menu simply stays up until you retry.
    if (choice !== 'YES') return;
    game.dialog = null;
    zoomBeforeDialog = null;    // he restarts at the door; the old view is stale
    spawnMoblin();
    placeLink(ENTRANCE);
    game.state = 'IDLE';
    drawHint();
    return;
  }
  const seat = game.dialog.seat;
  game.dialog = null;
  resumeZoom();                 // back to the magnification you were reading at
  // NO is "not this one", not "start over": Link stays on the seat he turned
  // down, and the player picks another by tapping it or stepping off.  The
  // dwell does not re-arm — he is already standing still on it.
  if (choice !== 'YES') {
    game.state = 'IDLE';
    game.pending = null;
    return;
  }
  game.state = 'SEATED';                  // optimistic; the stub cannot fail
  placeLink(seatCell(seat));
  drawHint();
  if (!await claimSeat(seat.id)) {        // Phase 2: a lost race lands here
    game.state = 'IDLE';                  // stay put; the room is still open
    drawHint();
  }
}

/* THE seam for Phase 2.  Today it writes the claim to this device so a reload
 * shows Link on the seat; tomorrow it runs the Firestore transaction against
 * the signed-in student's PID and returns whether the claim won.  Everything
 * else in this file already treats it as async and failable. */
async function claimSeat(seatId) {
  try {
    localStorage.setItem(CLAIM_KEY, seatId);
  } catch (err) {
    console.warn('claim not stored', err);   // private browsing; still seated
  }
  return true;
}

function restoreClaim() {
  // `?reset` starts from zero.  A phone has no console to type seating.reset()
  // into, and the claim survives a reload by design, so testing on a real device
  // needs a way in through the URL.  It stays on until the query is dropped.
  if (/[?&]reset\b/.test(location.search)) {
    try { localStorage.removeItem(CLAIM_KEY); } catch (err) { /* ignore */ }
  }
  let seatId = null;
  try { seatId = localStorage.getItem(CLAIM_KEY); } catch (err) { /* ignore */ }
  const seat = seatId && seatsById.get(seatId);
  if (!seat) return;
  placeLink(seatCell(seat));
  game.state = 'SEATED';
}

// --- the view ----------------------------------------------------------------

/* Pinch to zoom the map.  A seat is 16 art pixels across — about 3mm on a phone
 * — so leaning in has to be possible, and the browser's own pinch is the wrong
 * tool for it: it magnifies the whole page, legend and margins included, and on
 * iOS it is refused often enough that it could not be relied on.  So the map
 * zooms itself, inside the frame `#stage` clips.
 *
 * The zoom is carried by the canvas's CSS *width*, not by a scale transform:
 * widening it is the same upscale the page already does at rest, so the pixels
 * stay square at any magnification.  The pan is a translate on top.  Nothing
 * else in the file has to know — hit-testing goes through
 * getBoundingClientRect, which reports the zoomed, translated box already. */
const ZOOM_MAX = 4;
const view = { z: 1, x: 0, y: 0 };   // the canvas's top-left, stage-relative CSS px
let pinch = null;                    // a two-finger gesture's starting distance + view
let zoomBeforeDialog = null;

const stageBox = () => stage.getBoundingClientRect();
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

function applyView() {
  const box = stageBox();
  view.z = clamp(view.z, 1, ZOOM_MAX);
  // The map never leaves the frame.  At rest it fills it exactly, so both bounds
  // collapse onto 0 and there is nowhere to pan to.
  view.x = clamp(view.x, box.width * (1 - view.z), 0);
  view.y = clamp(view.y, box.height * (1 - view.z), 0);
  canvas.style.width = `${view.z * 100}%`;
  canvas.style.transform = `translate(${view.x}px, ${view.y}px)`;
}

// Zoom about a point (stage-relative CSS px): whatever is under it stays under it.
function zoomAt(z, px, py) {
  const next = clamp(z, 1, ZOOM_MAX);
  const k = next / view.z;
  view.x = px - (px - view.x) * k;
  view.y = py - (py - view.y) * k;
  view.z = next;
  applyView();
}

/* A message box takes the room back.  It is drawn in art coordinates, and at 4×
 * it is wider than the frame, so zoomed in it would sit half outside — and the
 * question matters more than the magnification.  The zoom returns when the box
 * closes, except after a death, where Link reappears at the door and the old
 * view would be looking somewhere else entirely. */
function suspendZoom() {
  pinch = null;
  if (view.z === 1) return;
  zoomBeforeDialog = { ...view };
  view.z = 1; view.x = 0; view.y = 0;
  applyView();
}

function resumeZoom() {
  if (!zoomBeforeDialog) return;
  Object.assign(view, zoomBeforeDialog);
  zoomBeforeDialog = null;
  applyView();
}

// --- input -------------------------------------------------------------------

const DIRECTIONS = {
  ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
};
const steering = () => game.state === 'IDLE' || game.state === 'WALKING';

/* The easter egg: one tile per press or swipe, and it overrides an autopilot
 * route so you can take the wheel mid-walk.  Nothing on the page advertises it. */
function stepBy(dc, dr) {
  if (!steering()) return;
  const at = linkCell();
  const ic = at.ic + dc, ir = at.ir + dr;
  if (!inRoom(ic, ir)) return;
  game.link.path = [{ ic, ir }];
  game.steered = true;
  game.pending = null;          // still moving: the last seat was passed through
  game.state = 'WALKING';
}

/* Picking Link up and putting him down.  A swipe moves him one tile per flick,
 * which is fine for a nudge and wrong for crossing the room — the natural thing
 * with a finger on a sprite is that the sprite comes with it.  So it does: while
 * the finger is down he is wherever it is (clamped to the interior — the walls
 * are not a place), and where it lifts is where he stands.
 *
 * A grab only becomes a drag once the finger has travelled DRAG_PX, so the grab
 * box can be generous — GRAB_PAD of slack around a 16px sprite, which a fingertip
 * needs — without stealing taps from the seats next to him. */
let grab = null;                // { id, ox, oy, live } — a finger resting on Link

const overLink = p =>
  p.x >= game.link.x - GRAB_PAD && p.x <= game.link.x + T + GRAB_PAD &&
  p.y >= game.link.y - GRAB_PAD && p.y <= game.link.y + T + GRAB_PAD;

function startDrag() {
  grab.live = true;
  game.state = 'DRAGGING';
  game.link.path.length = 0;    // the finger has the wheel now
  game.pending = null;
}

function dragLink(p) {
  const link = game.link;
  const x = clamp(p.x - grab.ox, cellX(0), cellX(ICOLS - 1));
  const y = clamp(p.y - grab.oy, cellY(0), cellY(IROWS - 1));
  const dx = x - link.x, dy = y - link.y;
  // Face the way he is being pulled, ignoring the jitter of a still finger.
  if (Math.max(Math.abs(dx), Math.abs(dy)) >= 1) {
    link.facing = Math.abs(dx) > Math.abs(dy)
      ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
  }
  link.walked += Math.abs(dx) + Math.abs(dy);   // keeps his legs going
  link.x = x;
  link.y = y;
}

/* Let go: he settles onto the nearest cell.  Letting go on a seat is as
 * deliberate as tapping one, so it asks at once — the dwell is for seats you
 * merely crossed, and a drop is not that.  `ask` is false when the gesture was
 * taken away rather than finished (a second finger, a cancel). */
function dropLink(ask) {
  const live = grab && grab.live;
  grab = null;
  if (!live) return;
  const cell = {
    ic: clamp(Math.round((game.link.x - WALL) / T), 0, ICOLS - 1),
    ir: clamp(Math.round((game.link.y - WALL) / T), 0, IROWS - 1),
  };
  placeLink(cell, game.link.facing);
  game.state = 'IDLE';
  const seat = seatAt(cell.ic, cell.ir);
  if (ask && isOpen(seat)) openDialog(seat);
}

function walkTo(seat) {
  const path = findPath(linkCell(), seatCell(seat));
  if (!path || !path.length) return;
  game.link.path = path;
  game.steered = false;
  game.pending = null;
  game.state = 'WALKING';
}

function canvasPoint(ev) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (ev.clientX - rect.left) * (canvas.width / rect.width),
    y: (ev.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function tap(ev) {
  const p = canvasPoint(ev);
  if (game.dialog) {
    const hit = game.dialog.options.find(o => o.hit &&
      p.x >= o.hit.x && p.x <= o.hit.x + o.hit.w &&
      p.y >= o.hit.y && p.y <= o.hit.y + o.hit.h);
    if (hit) answerDialog(hit.label);
    return;
  }
  if (!steering()) return;
  const ic = Math.floor((p.x - WALL) / T), ir = Math.floor((p.y - WALL) / T);
  if (!inRoom(ic, ir)) return;
  const seat = seatAt(ic, ir);
  if (!isOpen(seat)) return;               // closed seats and floor do nothing
  // Tapping the seat Link is already standing on asks again — the way back in
  // after a NO, since there is no route to walk and nothing else would happen.
  if (game.state === 'IDLE' &&
      game.link.x === cellX(ic) && game.link.y === cellY(ir)) openDialog(seat);
  else walkTo(seat);
}

/* One finger is a tap or a swipe; two are a pinch.  The moment a second finger
 * lands the gesture stops being a step — otherwise the fingers of a pinch lift
 * 100px apart and Link walks off.  `fingers` holds where each one is, which is
 * all a pinch needs: the distance between them is the zoom, the point between
 * them is the pan. */
let pointerStart = null;
const fingers = new Map();

// Distance and midpoint (stage-relative CSS px) of the two fingers down.
function spread() {
  const [a, b] = [...fingers.values()];
  const box = stageBox();
  return {
    d: Math.hypot(a.x - b.x, a.y - b.y),
    x: (a.x + b.x) / 2 - box.left,
    y: (a.y + b.y) / 2 - box.top,
  };
}

canvas.addEventListener('pointerdown', ev => {
  fingers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
  if (fingers.size > 1) {
    pointerStart = null;
    dropLink(false);            // a second finger means a pinch, not a carry
    // A pinch is measured against where it started, not against the last frame,
    // so a slow gesture cannot drift.
    if (fingers.size === 2 && !game.dialog) {
      const g = spread();
      pinch = { d: g.d, x: g.x, y: g.y, vx: view.x, vy: view.y, z: view.z };
    }
    return;
  }
  pointerStart = { x: ev.clientX, y: ev.clientY };
  canvas.focus({ preventScroll: true });
  const p = canvasPoint(ev);
  grab = !game.dialog && steering() && overLink(p)
    ? { id: ev.pointerId, ox: clamp(p.x - game.link.x, 0, T), oy: clamp(p.y - game.link.y, 0, T), live: false }
    : null;
  // Capture so a carry that wanders off the canvas still ends when the finger
  // or the button lifts, instead of leaving Link stuck to the cursor.  Touch
  // pointers capture implicitly, and a synthetic event has nothing to capture.
  try { if (grab) canvas.setPointerCapture(ev.pointerId); } catch (err) { /* not a live pointer */ }
});

canvas.addEventListener('pointermove', ev => {
  if (!fingers.has(ev.pointerId)) return;
  fingers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
  if (grab && grab.id === ev.pointerId && fingers.size === 1) {
    // Still inside the tap threshold: this may yet turn out to be a tap.
    if (!grab.live) {
      if (Math.hypot(ev.clientX - pointerStart.x, ev.clientY - pointerStart.y) < DRAG_PX) return;
      startDrag();
    }
    dragLink(canvasPoint(ev));
    return;
  }
  if (!pinch || fingers.size !== 2) return;
  const g = spread();
  const z = clamp(pinch.z * (g.d / pinch.d), 1, ZOOM_MAX);
  const k = z / pinch.z;
  // Hold the art under the gesture's midpoint at the gesture's midpoint: the
  // scale is about where the fingers started, the pan is how far they moved.
  view.z = z;
  view.x = g.x - (pinch.x - pinch.vx) * k;
  view.y = g.y - (pinch.y - pinch.vy) * k;
  applyView();
});

canvas.addEventListener('pointerup', ev => {
  const pinching = fingers.size > 1;
  fingers.delete(ev.pointerId);
  if (fingers.size < 2) pinch = null;
  if (grab && grab.id === ev.pointerId) {
    // A carry ends here; a grab that never moved falls through and is a tap.
    if (grab.live) { dropLink(true); pointerStart = null; return; }
    grab = null;
  }
  if (pinching || !pointerStart) { pointerStart = null; return; }
  const dx = ev.clientX - pointerStart.x, dy = ev.clientY - pointerStart.y;
  pointerStart = null;
  if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_PX) { tap(ev); return; }
  if (game.dialog) return;
  if (Math.abs(dx) > Math.abs(dy)) stepBy(Math.sign(dx), 0);
  else stepBy(0, Math.sign(dy));
});

canvas.addEventListener('pointercancel', ev => {
  fingers.delete(ev.pointerId);
  if (fingers.size < 2) pinch = null;
  if (grab && grab.id === ev.pointerId) dropLink(false);
  pointerStart = null;
});

// Trackpad pinches arrive as ctrl+wheel and mouse wheels as themselves; neither
// has a page to scroll here, so both zoom.
canvas.addEventListener('wheel', ev => {
  if (game.dialog) return;
  ev.preventDefault();
  const box = stageBox();
  const rate = ev.ctrlKey ? 0.02 : 0.0025;
  zoomAt(view.z * Math.exp(-ev.deltaY * rate), ev.clientX - box.left, ev.clientY - box.top);
}, { passive: false });

// Safari before 13 ignores touch-action, and would zoom the page instead.
stage.addEventListener('gesturestart', ev => ev.preventDefault());

// A rotation changes what the frame can hold, so the pan has to be re-checked.
window.addEventListener('resize', applyView);

window.addEventListener('keydown', ev => {
  if (game.dialog) {
    if (ev.key === 'Enter' || ev.key === ' ') {
      answerDialog(game.dialog.choice);
    } else if (ev.key === 'Escape') {
      answerDialog('NO');
    } else if (DIRECTIONS[ev.key]) {
      game.dialog.choice = game.dialog.choice === 'YES' ? 'NO' : 'YES';
    } else {
      return;
    }
    ev.preventDefault();
    return;
  }
  const dir = DIRECTIONS[ev.key];
  if (!dir) return;
  ev.preventDefault();                     // arrows steer Link, not the page
  stepBy(dir[0], dir[1]);
});

// For testing a second claim on the same device — not part of the student flow.
window.seating = {
  reset() { localStorage.removeItem(CLAIM_KEY); location.reload(); },
  game,
  view,
  zoom(z) { zoomAt(z, stageBox().width / 2, stageBox().height / 2); },
};

boot().catch(err => {
  console.error(err);
  document.body.textContent = 'Could not load the seating map.';
});
})();
