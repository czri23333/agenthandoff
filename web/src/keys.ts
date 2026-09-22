// The keyboard layer of the cockpit, kept out of App.tsx so a list view can ask
// "is the focus inside my rows?" without importing the app shell (App renders the
// views, so an import the other way is a cycle).

/** Focus inside this means the reader is navigating, not watching. */
export const ROW_SCOPE = "button.ah-row, button.ah-more";
const ROW_SELECTOR = "button.ah-row";
const MORE_SELECTOR = "button.ah-more";

/** True when `a` comes before `b` in document order. */
function precedes(a: Element, b: Element): boolean {
  return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

/**
 * Move the keyboard cursor between session rows.
 *
 * Rows are native `<button>`s, so *moving focus* is the whole feature: Enter and
 * Space activate without another handler, `:focus-visible` keeps a mouse click
 * from looking like a keyboard selection, and the selection never follows the
 * pointer, because reading a row with the mouse is not selecting it. PageUp/Page
 * step a half screen so the cursor never lands off-view.
 *
 * Walking off the rendered end pages more rows in rather than stopping, which is
 * what a reader expects from a list longer than a page. Both ends of that are
 * resolved by *document order* rather than by index or by `querySelector`: a
 * grouped list holds one expander per group, so a document-first lookup would
 * page in rows for the wrong group than the one the cursor left. And a group's
 * rows are `<li>`s that can nest sub-agent rows, so a sibling walk would stop
 * inside a child list. After the click the new cursor is "a row node that did not
 * exist a frame ago", which survives the insertion shifting every index below it.
 *
 * @returns true when the key was consumed, so the shell leaves it alone.
 */
export function rowNav(e: KeyboardEvent): boolean {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(ROW_SELECTOR));
  if (!rows.length) return false;
  const active = document.activeElement as HTMLElement | null;
  const last = rows.length - 1;
  const idx = active ? rows.indexOf(active) : -1;
  // From the expander itself ArrowUp must reach the last row: it sits one slot
  // past the final row.
  const at = active && idx < 0 && active.matches(MORE_SELECTOR) ? last + 1 : idx;
  const rowHeight = rows[0].getBoundingClientRect().height || 40;
  const page = Math.max(1, Math.round(window.innerHeight / rowHeight / 2));
  let step = 0;
  switch (e.key) {
    case "ArrowDown":
    case "j":
      step = 1;
      break;
    case "PageDown":
      step = page;
      break;
    case "ArrowUp":
    case "k":
      step = -1;
      break;
    case "PageUp":
      step = -page;
      break;
    case "Home":
      step = -rows.length;
      break;
    case "End":
      step = rows.length;
      break;
    default:
      return false;
  }
  e.preventDefault();
  if (step > 0 && at >= last) {
    const expanders = Array.from(document.querySelectorAll<HTMLElement>(MORE_SELECTOR));
    const expander = expanders.find((b) => active === null || precedes(active, b));
    if (!expander) {
      rows[last]?.focus(); // nothing left to page in; park on the final row
      return true;
    }
    const known = new Set(rows);
    expander.click();
    requestAnimationFrame(() => {
      const grown = Array.from(document.querySelectorAll<HTMLElement>(ROW_SELECTOR)).filter(
        (r) => !known.has(r)
      );
      const target =
        grown[Math.min(step, grown.length) - 1] ?? grown[grown.length - 1] ?? rows[last];
      target?.focus();
      target?.scrollIntoView({ block: "nearest" });
    });
    return true;
  }
  const target = rows[Math.max(0, Math.min(last, at + step))];
  target?.focus();
  target?.scrollIntoView({ block: "nearest" });
  return true;
}

