/// Type, ported from `frontend/src/design.ts`.
///
/// Three families, each with one job:
///
///   IBM Plex Sans   all interface and body text
///   IBM Plex Mono   figures and data
///   Fraunces        display only — never below 24, never body, never interface
///
/// The fonts are bundled as assets rather than fetched at runtime. A dealership
/// employee opening this on a lot with no signal must not see a fallback face,
/// and a font that arrives a second late is a visible reflow.
library;

import 'package:flutter/widgets.dart';

import 'tokens.dart';

abstract final class Fonts {
  static const sans = 'IBMPlexSans';
  static const mono = 'IBMPlexMono';
  static const serif = 'Fraunces';
}

/// Text styles.
///
/// Sizes match the web client so the two read as one product.
abstract final class T {
  // ── Interface and body ──

  static const body = TextStyle(
    fontFamily: Fonts.sans,
    fontSize: 15,
    height: 1.55,
    color: C.ink,
  );

  static const bodySmall = TextStyle(
    fontFamily: Fonts.sans,
    fontSize: 14,
    height: 1.55,
    color: C.inkSoft,
  );

  static const label = TextStyle(
    fontFamily: Fonts.sans,
    fontSize: 14,
    fontWeight: FontWeight.w500,
    color: C.ink,
  );

  /// Field labels and small uppercase captions. Mono because they sit beside
  /// data and the letterforms should agree with it.
  static const caption = TextStyle(
    fontFamily: Fonts.mono,
    fontSize: 11,
    letterSpacing: 0.88, // 0.08em at 11px
    color: C.inkSoft,
  );

  /// Figures. Anything countable — a stock number, an image count, a price.
  static const figure = TextStyle(
    fontFamily: Fonts.mono,
    fontSize: 13,
    color: C.ink,
  );
}

/// Fraunces at a given size, with the optical-size axis tracked to it.
///
/// Fraunces is a variable font whose `opsz` axis changes stroke contrast:
/// higher values thin the hairlines, which is correct on a large display line
/// and nearly invisible on a small one. The web codebase encodes this rule
/// rather than documenting it, because the defect that produced it — opsz 144
/// applied at 14px, where the hairlines all but disappeared — could otherwise
/// recur by accident. Encoding it here means it cannot recur on mobile either.
///
/// Display only. The assertion is the whole point: Fraunces below 24 is a
/// mistake the type system cannot catch, so it is caught at runtime in debug.
TextStyle serif(double size, {Color color = C.ink, FontWeight? weight}) {
  assert(
    size >= 24,
    'Fraunces is display only and must never be used below 24px. '
    'Interface and body text use IBM Plex Sans — see T.body and T.label.',
  );

  return TextStyle(
    fontFamily: Fonts.serif,
    fontSize: size,
    color: color,
    fontWeight: weight ?? FontWeight.w400,
    letterSpacing: size * -0.02, // -0.02em, matching the web headings
    height: 1.1,
    fontVariations: [
      FontVariation('opsz', size > 40 ? 144 : 72),
      FontVariation('wght', (weight ?? FontWeight.w400).value.toDouble()),
    ],
  );
}
