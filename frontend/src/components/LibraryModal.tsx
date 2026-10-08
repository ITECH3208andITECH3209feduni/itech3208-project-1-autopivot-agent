
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

const openDialogs: symbol[] = []

let savedOverflow = ''
let savedPaddingRight = ''

function lockPageScroll() {
  const { body } = document
  savedOverflow = body.style.overflow
  savedPaddingRight = body.style.paddingRight
  const gap = window.innerWidth - document.documentElement.clientWidth
  body.style.overflow = 'hidden'
  if (gap > 0) body.style.paddingRight = `${gap}px`
}

function unlockPageScroll() {
  document.body.style.overflow = savedOverflow
  document.body.style.paddingRight = savedPaddingRight
}

export function useDialogKeys({
  active,
  onClose,
  containerRef,
}: {
  active: boolean
  onClose: () => void
  containerRef?: RefObject<HTMLElement | null>
}) {
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
  label: string
  maxWidth?: number
  children: ReactNode
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useDialogKeys({ active: true, onClose, containerRef })

  useEffect(() => {
    containerRef.current?.closest('[role="dialog"]')?.setAttribute('aria-label', label)
  }, [label])

  return (
    <Modal onClose={onClose} maxWidth={maxWidth}>
      <div
        ref={containerRef}
        tabIndex={-1}
        style={{
          outline: 'none',
          maxHeight: 'calc(100vh - 48px)',
          overflowY: 'auto',
        }}
      >
        {children}
      </div>
    </Modal>
  )
}
