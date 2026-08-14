// A dialog that behaves like one, wrapped around the shared Modal primitive.
//
// `Modal` draws the correct surface — dimmed ink ground at 55% with blur, white
// card, closes on a backdrop click — but it does nothing about the keyboard.
// Escape is ignored, Tab walks straight out of the dialog and into the page
// behind it, and when the dialog closes focus is left wherever it happened to
// be, which for a keyboard user means being dropped back at the top of the
// document. The primitive is owned elsewhere in this rebuild, so the missing
// behaviour is added around it here rather than by editing it.
//
// The escape hatch at the bottom — setting aria-label on the primitive's own
// dialog element — exists for the same reason: Modal accepts no ARIA props, so
// an unnamed dialog is announced as just "dialog" unless it is labelled after
// the fact.

import { useEffect, useRef, type ReactNode, type RefObject } from 'react'

import { Modal } from './primitives'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

// Dialogs stack: a delete confirmation opens over a preview. Only the topmost
// one may act on Escape, or one keypress would dismiss the entire stack.
const openDialogs: symbol[] = []

// Saved once, when the first dialog opens, and put back when the last closes.
let savedOverflow = ''
let savedPaddingRight = ''

function lockPageScroll() {
  const { body } = document
  savedOverflow = body.style.overflow
  savedPaddingRight = body.style.paddingRight
  // Removing the scrollbar reflows the page underneath the dialog, which is
  // visible as a sideways jump through the translucent ground. Its width is
  // given back as padding so nothing moves.
  const gap = window.innerWidth - document.documentElement.clientWidth
  body.style.overflow = 'hidden'
  if (gap > 0) body.style.paddingRight = `${gap}px`
}

function unlockPageScroll() {
  document.body.style.overflow = savedOverflow
  document.body.style.paddingRight = savedPaddingRight
}

/**
 * Escape to close, Tab confined to the dialog, and focus returned to whatever
 * opened it.
 *
 * Exported on its own because `ConfirmDialog` renders `Modal` itself and gives
 * callers no element to hold on to: without a container it can still be given
 * Escape and focus restoration, which is most of the gap.
 */
export function useDialogKeys({
  active,
  onClose,
  containerRef,
}: {
  active: boolean
  onClose: () => void
  containerRef?: RefObject<HTMLElement | null>
}) {
  // Held in a ref so a new inline onClose on every render does not tear the
  // listener down and put it back, which would lose the dialog's place in the
  // stack and re-steal focus.
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose })

  useEffect(() => {
    if (!active) return

    const token = Symbol('dialog')
    openDialogs.push(token)
    if (openDialogs.length === 1) lockPageScroll()

    const opener = document.activeElement as HTMLElement | null

    function focusableItems(container: HTMLElement): HTMLElement[] {
      return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
        // offsetParent is null for anything display:none, which would otherwise
        // become a stop on the tab ring that focuses nothing.
        .filter(element => element.offsetParent !== null)
    }

    function onKeyDown(event: KeyboardEvent) {
      if (openDialogs[openDialogs.length - 1] !== token) return

      if (event.key === 'Escape') {
        event.stopPropagation()
        closeRef.current()
        return
      }

      if (event.key !== 'Tab') return
      const container = containerRef?.current
      if (!container) return

      const items = focusableItems(container)
      if (items.length === 0) {
        event.preventDefault()
        container.focus()
        return
      }

      const first = items[0]
      const last = items[items.length - 1]
      const activeElement = document.activeElement as HTMLElement | null

      if (!activeElement || !container.contains(activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    // Capture phase: the dialog answers Escape before anything inside it can.
    document.addEventListener('keydown', onKeyDown, true)

    const container = containerRef?.current
    if (container) {
      const [first] = focusableItems(container)
      ;(first ?? container).focus()
    }

    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      const index = openDialogs.indexOf(token)
      if (index >= 0) openDialogs.splice(index, 1)
      if (openDialogs.length === 0) unlockPageScroll()
      // Only if the opener is still on the page: the button that opened a
      // delete confirmation is gone by the time the deletion finishes.
      if (opener && document.contains(opener)) opener.focus()
    }
  }, [active, containerRef])
}

export default function LibraryModal({
  onClose,
  label,
  maxWidth = 1040,
  children,
}: {
  onClose: () => void
  /** Names the dialog for a screen reader; without it it is just "dialog". */
  label: string
  maxWidth?: number
  children: ReactNode
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useDialogKeys({ active: true, onClose, containerRef })

  useEffect(() => {
    // Modal owns the element carrying role="dialog" and takes no ARIA props, so
    // the name is applied to it directly. Reaching up the tree is unpleasant,
    // but it is the only way to name the dialog without editing a file another
    // agent owns.
    containerRef.current?.closest('[role="dialog"]')?.setAttribute('aria-label', label)
  }, [label])

  return (
    <Modal onClose={onClose} maxWidth={maxWidth}>
      <div
        ref={containerRef}
        tabIndex={-1}
        style={{
          outline: 'none',
          // The dialog must never grow past the viewport: Modal's card clips
          // its overflow, so anything taller would be unreachable rather than
          // merely off-screen.
          maxHeight: 'calc(100vh - 48px)',
          overflowY: 'auto',
        }}
      >
        {children}
      </div>
    </Modal>
  )
}
