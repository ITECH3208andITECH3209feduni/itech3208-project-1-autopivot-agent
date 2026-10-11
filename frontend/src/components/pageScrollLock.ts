// The page behind a dialog must not scroll, and there is only one page.
//
// This used to be done twice over. `Modal` saved document.body.style.overflow
// when it opened and wrote its copy back when it closed, and `useDialogKeys`
// kept a second copy of its own. The removal confirmation runs both, and React
// runs the child's effect first, so the second save recorded the first one's
// 'hidden' as though it were the page's own value. On close React tears the
// child down first as well, which made that stale 'hidden' the last word: the
// app shell scrolls on the body, so every screen stayed frozen until a reload.
//
// Two copies of one piece of state will always find an order in which they
// disagree. So there is a single lock, counted: the page's own values are read
// when the first hold is taken and put back when the last is let go, whatever
// order the holders let go in.

let holds = 0
let saved = { overflow: '', paddingRight: '' }

/** Stops the page scrolling. The returned function lets go of this hold. */
export function lockPageScroll(): () => void {
  const { body } = document

  if (holds === 0) {
    saved = { overflow: body.style.overflow, paddingRight: body.style.paddingRight }
    // Removing the scrollbar reflows the page underneath the dialog, which is
    // visible as a sideways jump through the translucent ground. Its width is
    // given back as padding so nothing moves. Measured before the scrollbar
    // goes, because afterwards there is nothing left to measure.
    const gap = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (gap > 0) body.style.paddingRight = `${gap}px`
  }
  holds += 1

  let released = false
  return () => {
    // Letting go twice must not spend a hold that belongs to another dialog.
    if (released) return
    released = true
    holds -= 1
    if (holds === 0) {
      body.style.overflow = saved.overflow
      body.style.paddingRight = saved.paddingRight
    }
  }
}
