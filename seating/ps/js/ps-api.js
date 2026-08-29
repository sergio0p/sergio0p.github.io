/* The group's submission, held by the server instead of the browser.
 *
 * This replaces ps-store.js and ps-progress.js, which kept everything in
 * localStorage. That was per device, and problem sets are group work, so the
 * two facts could not both be true: one partner submitted Part I, the other
 * opened the page on their own laptop, saw an empty form, and was told "Part I
 * is still outstanding" -- which was false. Neither could see what the group had
 * actually filed, and the group acknowledgement never fired for either of them.
 *
 * Everything here is one round trip to the service, which resolves the caller's
 * group from the frozen psGroups snapshot and holds submissions append-only.
 * The page reads one state object and never has to reconcile two sources.
 *
 * The identity is the session cookie from the seating gate. There is no `group`
 * parameter any more: a student cannot name the group they are submitting for,
 * because the server already knows and would not believe them anyway.
 */

let state = null;
let ps = null;

/** Load the group's state. Call once, before anything is rendered. */
export async function psInit(id) {
  ps = id;
  try {
    const r = await fetch(`/api/ps/${ps}/me`, { credentials: 'same-origin' });
    if (r.status === 404) {
      // No cookie, or a problem set this service does not serve. The gate
      // returns the same 404 for both, deliberately, so the page cannot tell
      // them apart either -- and does not need to.
      state = { error: 'no_session' };
      return state;
    }
    if (!r.ok) throw new Error(`${r.status}`);
    state = await r.json();
  } catch (err) {
    state = { error: 'offline', detail: String(err) };
  }
  return state;
}

export function psState() { return state; }

/** The group's name, or null when the student has no group for this round. */
export function psGroupName() {
  return state && state.group ? state.group.groupName : null;
}

/** Member names, for the confirmation -- surnames alone go ambiguous. */
export function psMembers() {
  return state && state.group ? state.group.members.map(m => m.name) : [];
}

/** The last version's answers for one part, or null if it was never filed. */
export function psAnswers(part) {
  const sub = state && state.submission;
  return sub && sub.answers && part in sub.answers ? sub.answers[part] : null;
}

export function psPartsIn() {
  const sub = state && state.submission;
  return sub ? sub.parts.slice() : [];
}

export function psIsComplete(parts) {
  const have = psPartsIn();
  return parts.every(p => have.includes(p));
}

/** Everything left blank across every part filed so far, in part order. */
export function psBlanks(order) {
  const sub = state && state.submission;
  if (!sub || !sub.blanks) return [];
  return (order || Object.keys(sub.blanks)).flatMap(p => sub.blanks[p] || []);
}

/** Who filed the version currently on record, or null. */
export function psSubmittedBy() {
  const sub = state && state.submission;
  return sub ? sub.submittedBy : null;
}

export function psClosed() { return !!(state && state.closed); }
export function psDue() { return state ? state.due : null; }

/**
 * File one part. The server merges it over the previous version's answers and
 * appends a new version, so filing Part II cannot wipe Part I.
 * Returns { ok, version, late } or { ok: false, error }.
 */
export async function psSubmit(part, answers, blanks) {
  try {
    const r = await fetch(`/api/ps/${ps}/submit`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part, answers, blanks: blanks || [] }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      return { ok: false, error: body.error || `http_${r.status}` };
    }
    const out = await r.json();
    await psInit(ps);           // re-read, so the page shows what was stored
    return { ok: true, ...out };
  } catch (err) {
    return { ok: false, error: 'offline' };
  }
}

/* What to put on screen when there is nothing to submit against. Both cases are
   dead ends for the student, and both need to say what to do rather than fail
   silently. */
export function psBlockingMessage() {
  if (!state) return 'Loading…';
  if (state.error === 'no_session') {
    return 'Open this page from your personal link — it is in your Canvas '
         + 'inbox. The link signs you in; this page cannot do it on its own.';
  }
  if (state.error === 'offline') {
    return 'Could not reach the server. Check your connection and reload — '
         + 'nothing you have typed has been submitted yet.';
  }
  if (!state.group) {
    return 'You are not in a group for this problem set. Email the instructor '
         + 'before the due date and it will be sorted out.';
  }
  return null;
}
