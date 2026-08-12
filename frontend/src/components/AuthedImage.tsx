// Stored files sit behind bearer auth, so a plain <img src="/api/files/…"> gets
// a 401 — the browser does not attach the Authorization header to image
// requests. This fetches the bytes, wraps them in an object URL, and revokes it
// on unmount so the blobs do not accumulate.

import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { C } from '../design'

export default function AuthedImage({
  src, alt, style,
}: {
  src: string
  alt: string
  style?: React.CSSProperties
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = false
    let created: string | null = null

    api.fetchFile(src)
      .then(url => {
        if (revoked) {
          URL.revokeObjectURL(url)
          return
        }
        created = url
        setObjectUrl(url)
      })
      .catch(() => setFailed(true))

    return () => {
      revoked = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [src])

  if (failed || !objectUrl) {
    return <div style={{ background: C.line, ...style }} aria-label={failed ? `${alt} — unavailable` : undefined} />
  }

  return <img src={objectUrl} alt={alt} style={{ objectFit: 'cover', ...style }} />
}
