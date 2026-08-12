// Placeholder photography for the landing page, lifted from the Figma Make
// export.
//
// These are Unsplash stock images, not AutoPivot output. Note that several
// backdrop variants resolve to the SAME photograph — cx5-studio-grey-front3q,
// cx5-forecourt-front3q and cx5-open-sky-front3q are all photo-1617469767068 —
// so switching backdrop in the configurator currently changes nothing on
// screen. The section claims "Any vehicle. Any backdrop. Any angle." and does
// not yet demonstrate it. Replacing this with a real 3x3x6 matrix of pipeline
// renders is tracked separately.

import { UNSPLASH } from '../design'

export const RESULT_IMAGES: Record<string, string> = {
  'cx5-studio-grey-front3q':  UNSPLASH('photo-1617469767068-d84dc5a9d404'),
  'cx5-studio-grey-front':    UNSPLASH('photo-1494976388531-d1058494cdd8'),
  'cx5-studio-grey-side':     UNSPLASH('photo-1542282088-72c9c27ed0cd'),
  'cx5-studio-grey-rear3q':   UNSPLASH('photo-1555215695-3004980ad54e'),
  'cx5-studio-grey-interior': UNSPLASH('photo-1503376780353-7e6692767b70'),
  'cx5-studio-grey-wheel':    UNSPLASH('photo-1615563868638-98253a7dc33b'),
  'cx5-forecourt-front3q':    UNSPLASH('photo-1617469767068-d84dc5a9d404'),
  'cx5-forecourt-front':      UNSPLASH('photo-1494976388531-d1058494cdd8'),
  'cx5-forecourt-side':       UNSPLASH('photo-1574023278969-abb7ab49945c'),
  'cx5-forecourt-rear3q':     UNSPLASH('photo-1555215695-3004980ad54e'),
  'cx5-forecourt-interior':   UNSPLASH('photo-1503376780353-7e6692767b70'),
  'cx5-forecourt-wheel':      UNSPLASH('photo-1615563868638-98253a7dc33b'),
  'cx5-open-sky-front3q':     UNSPLASH('photo-1617469767068-d84dc5a9d404'),
  'cx5-open-sky-front':       UNSPLASH('photo-1494976388531-d1058494cdd8'),
  'cx5-open-sky-side':        UNSPLASH('photo-1542282088-72c9c27ed0cd'),
  'cx5-open-sky-rear3q':      UNSPLASH('photo-1553440569-bcc63803a83d'),
  'cx5-open-sky-interior':    UNSPLASH('photo-1503376780353-7e6692767b70'),
  'cx5-open-sky-wheel':       UNSPLASH('photo-1615563868638-98253a7dc33b'),
  'hilux-studio-grey-front3q':  UNSPLASH('photo-1502877338535-766e1452684a'),
  'hilux-studio-grey-front':    UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'hilux-studio-grey-side':     UNSPLASH('photo-1547038577-da80abbc4f19'),
  'hilux-studio-grey-rear3q':   UNSPLASH('photo-1525609004556-c46c7d6cf023'),
  'hilux-studio-grey-interior': UNSPLASH('photo-1585390062628-be8608aa7d83'),
  'hilux-studio-grey-wheel':    UNSPLASH('photo-1562141961-b7c91e403f02'),
  'hilux-forecourt-front3q':    UNSPLASH('photo-1502877338535-766e1452684a'),
  'hilux-forecourt-front':      UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'hilux-forecourt-side':       UNSPLASH('photo-1547038577-da80abbc4f19'),
  'hilux-forecourt-rear3q':     UNSPLASH('photo-1525609004556-c46c7d6cf023'),
  'hilux-forecourt-interior':   UNSPLASH('photo-1585390062628-be8608aa7d83'),
  'hilux-forecourt-wheel':      UNSPLASH('photo-1562141961-b7c91e403f02'),
  'hilux-open-sky-front3q':     UNSPLASH('photo-1502877338535-766e1452684a'),
  'hilux-open-sky-front':       UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'hilux-open-sky-side':        UNSPLASH('photo-1574023240744-64c47c8c0676'),
  'hilux-open-sky-rear3q':      UNSPLASH('photo-1525609004556-c46c7d6cf023'),
  'hilux-open-sky-interior':    UNSPLASH('photo-1585390062628-be8608aa7d83'),
  'hilux-open-sky-wheel':       UNSPLASH('photo-1562141961-b7c91e403f02'),
  'ranger-studio-grey-front3q':  UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'ranger-studio-grey-front':    UNSPLASH('photo-1502877338535-766e1452684a'),
  'ranger-studio-grey-side':     UNSPLASH('photo-1574023278969-abb7ab49945c'),
  'ranger-studio-grey-rear3q':   UNSPLASH('photo-1547038577-da80abbc4f19'),
  'ranger-studio-grey-interior': UNSPLASH('photo-1503376780353-7e6692767b70'),
  'ranger-studio-grey-wheel':    UNSPLASH('photo-1615563868638-98253a7dc33b'),
  'ranger-forecourt-front3q':    UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'ranger-forecourt-front':      UNSPLASH('photo-1502877338535-766e1452684a'),
  'ranger-forecourt-side':       UNSPLASH('photo-1574023240744-64c47c8c0676'),
  'ranger-forecourt-rear3q':     UNSPLASH('photo-1547038577-da80abbc4f19'),
  'ranger-forecourt-interior':   UNSPLASH('photo-1503376780353-7e6692767b70'),
  'ranger-forecourt-wheel':      UNSPLASH('photo-1615563868638-98253a7dc33b'),
  'ranger-open-sky-front3q':     UNSPLASH('photo-1563720223185-11069c9a3ba2'),
  'ranger-open-sky-front':       UNSPLASH('photo-1502877338535-766e1452684a'),
  'ranger-open-sky-side':        UNSPLASH('photo-1574023278969-abb7ab49945c'),
  'ranger-open-sky-rear3q':      UNSPLASH('photo-1525609004556-c46c7d6cf023'),
  'ranger-open-sky-interior':    UNSPLASH('photo-1503376780353-7e6692767b70'),
  'ranger-open-sky-wheel':       UNSPLASH('photo-1615563868638-98253a7dc33b'),
}

export const VEHICLE_THUMBS: Record<string, string> = {
  cx5:    UNSPLASH('photo-1617469767068-d84dc5a9d404', 144, 96),
  hilux:  UNSPLASH('photo-1502877338535-766e1452684a', 144, 96),
  ranger: UNSPLASH('photo-1563720223185-11069c9a3ba2', 144, 96),
}

export const ANGLE_THUMBS: Record<string, string> = {
  front3q:  UNSPLASH('photo-1494976388531-d1058494cdd8', 192, 128),
  front:    UNSPLASH('photo-1542282088-72c9c27ed0cd', 192, 128),
  side:     UNSPLASH('photo-1555215695-3004980ad54e', 192, 128),
  rear3q:   UNSPLASH('photo-1547038577-da80abbc4f19', 192, 128),
  interior: UNSPLASH('photo-1503376780353-7e6692767b70', 192, 128),
  wheel:    UNSPLASH('photo-1615563868638-98253a7dc33b', 192, 128),
}
