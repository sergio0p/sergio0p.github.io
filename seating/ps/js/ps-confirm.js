/* The one dialog that matters: handing the problem set in.
 *
 * It carries two jobs and no others. It names the group, because one student
 * submits for the pair and the wrong name here is the mistake nobody catches
 * afterwards. And it says what is still blank -- but only here, at the end.
 * Warning on every intermediate submit would train students to dismiss it, and
 * a group is entitled to hand in an unfinished set and finish it later.
 *
 * Both parts share this because they must say the same thing; the two pages
 * style their own dialogs, and only the hooks are common.
 */

/** "a", "a and b", "a, b and c" -- an English list, not a comma soup. */
export function series(items) {
  if (items.length < 2) return items.join('');
  return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
}

/**
 * Fill a confirmation dialog and set its buttons to match the situation.
 * @param {HTMLDialogElement} dialog
 * @param {{group: string, blanks: string[]}} state
 */
export function prepareConfirm(dialog, state) {
  const blanks = state.blanks || [];
  const q = sel => dialog.querySelector(sel);

  q('[data-confirm-group]').textContent = state.group;

  const warn = q('[data-confirm-warning]');
  warn.hidden = blanks.length === 0;
  if (blanks.length) {
    warn.innerHTML = 'Nothing is recorded for <strong>' + series(blanks) +
      '</strong>. Handing in now leaves ' +
      (blanks.length === 1 ? 'it' : 'them') + ' unanswered.';
  }

  // The labels change with the situation, because the same press means
  // something different when work is missing.
  q('[data-confirm-cancel]').textContent = blanks.length
    ? 'Go back and finish' : 'Not my group';
  q('[data-confirm-yes]').textContent = blanks.length
    ? 'Hand it in anyway' : 'Hand it in';
}
