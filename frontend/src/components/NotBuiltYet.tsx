// A deliberate placeholder for screens whose backend does not exist yet.
//
// The alternative — keeping the Figma mock data — means a screen that looks
// finished and reports invented vehicles, angles and confidence scores. For a
// tool whose job is judging output quality, that is the worst possible thing to
// fake. These say plainly what is missing.

import { C, MONO, SANS, serif } from '../design'

export default function NotBuiltYet({
  title, blurb, waitingOn,
}: {
  title: string
  blurb: string
  waitingOn: string[]
}) {
  return (
    <div>
      <h1 style={{ ...serif(40), color: C.ink, margin: '0 0 32px', letterSpacing: '-0.02em', lineHeight: 1 }}>
        {title}
      </h1>

      <div style={{
        border: `1px dashed ${C.lineStrong}`, borderRadius: 16,
        padding: '48px 40px', maxWidth: 640,
      }}>
        <p style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: C.inkSoft,
          textTransform: 'uppercase', margin: '0 0 16px',
        }}>
          Not built yet
        </p>
        <p style={{ fontFamily: SANS, fontSize: 16, color: C.ink, margin: '0 0 24px', lineHeight: 1.6 }}>
          {blurb}
        </p>
        <p style={{
          fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em', color: C.inkSoft,
          textTransform: 'uppercase', margin: '0 0 10px',
        }}>
          Waiting on
        </p>
        <ul style={{
          fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0,
          paddingLeft: 20, lineHeight: 1.8,
        }}>
          {waitingOn.map(item => <li key={item}>{item}</li>)}
        </ul>
      </div>
    </div>
  )
}
