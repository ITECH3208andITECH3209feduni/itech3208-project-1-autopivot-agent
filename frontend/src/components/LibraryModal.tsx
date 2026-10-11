
import { useEffect, useRef, type ReactNode, type RefObject } from 'react'

import { lockPageScroll } from './pageScrollLock'
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
    const releaseScroll = lockPageScroll()

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
      releaseScroll()
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
