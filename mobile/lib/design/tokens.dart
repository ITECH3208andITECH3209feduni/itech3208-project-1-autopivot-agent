/// The visual system, ported from `frontend/src/design.ts`.
///
/// That file is the single source of truth for the product's appearance, and
/// this is its mobile counterpart. Values are copied deliberately rather than
/// approximated: the mobile application has to read as the same product as the
/// web one, and a colour that is nearly right is worse than an obvious mistake
/// because nobody notices it until the two are side by side.
///
/// Nothing outside this file may declare a colour, a radius or a spacing value.
/// The web codebase carries a comment about exactly that drift, and it had
/// already started before it was caught.
library;

import 'package:flutter/widgets.dart';

/// Colours.
///
/// The names match `design.ts` exactly so a value can be traced between the two
/// codebases without translation.
abstract final class C {
  // ── Grounds ──
  static const ink = Color(0xFF1A1A17);
  static const inkSoft = Color(0xFF4A4A44);
  static const bone = Color(0xFFF5F2EC);
  static const paper = Color(0xFFFBFAF8);
  static const white = Color(0xFFFFFFFF);

  // ── Lines ──

  /// Decorative dividers only. Measures 1.29:1 against paper, which WCAG
  /// exempts for decoration but which fails 1.4.11 for anything interactive.
  static const line = Color(0xFFE2DED6);

  /// The border of any interactive control. 3.53:1, which clears the 3:1 that
  /// WCAG 1.4.11 requires for a component boundary.
  static const lineStrong = Color(0xFF878580);

  // ── Accent ──

  /// The only accent in the product. Forest means "you can act here" and
  /// carries no other meaning. Resist adding a second.
  static const forest = Color(0xFF1F4D3A);
  static const forestLift = Color(0xFF2A6B4F);
  static const forestTint = Color(0x0F1F4D3A); // rgba(31,77,58,0.06)

  // ── Status ──
  //
  // Status colours describe a pipeline state and never carry brand meaning.
  // There is deliberately no success colour: completion is shown by the
  // processed photograph appearing, not by turning something green.

  /// Progress tracks only, where 3:1 suffices for a non-text boundary.
  static const amber = Color(0xFFB8791A);

  /// Amber as label text. 4.60:1 on amberTint, where plain amber reaches only
  /// 3.12:1 and fails for body text.
  static const amberText = Color(0xFF936014);
  static const amberTint = Color(0x1AB8791A); // rgba(184,121,26,0.1)

  static const rust = Color(0xFFA33A28);
  static const rustTint = Color(0x1AA33A28); // rgba(163,58,40,0.1)
}

/// Corner radii. Two values, and no others.
///
/// From guidelines §7. A radius outside this pair is a mistake rather than a
/// decision, which is why they are named for their use and not their size.
abstract final class Radii {
  static const card = 16.0;
  static const control = 10.0;

  static const cardAll = BorderRadius.all(Radius.circular(card));
  static const controlAll = BorderRadius.all(Radius.circular(control));
}

/// The 8px spacing scale.
///
/// Every gap, pad and inset comes from here. A value off the scale is a
/// mistake, not a decision — same rule as the radii.
abstract final class Space {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 16.0;
  static const lg = 24.0;
  static const xl = 32.0;
  static const xxl = 48.0;
}

/// The card shadow from `design.ts`, which is two layers rather than one: a
/// tight contact shadow and a wider ambient one. A single blurred shadow reads
/// as a drop shadow; this reads as a surface lifted off the page.
const cardShadow = <BoxShadow>[
  BoxShadow(
    color: Color(0x0F1A1A17), // rgba(26,26,23,0.06)
    blurRadius: 3,
    offset: Offset(0, 1),
  ),
  BoxShadow(
    color: Color(0x0A1A1A17), // rgba(26,26,23,0.04)
    blurRadius: 12,
    offset: Offset(0, 4),
  ),
];
