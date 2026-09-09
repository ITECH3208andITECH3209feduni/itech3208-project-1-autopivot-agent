/// The Flutter theme, assembled from the tokens.
///
/// Widgets read from here or from [C] and [T] directly. Nothing declares a
/// colour or a size of its own — see the note at the top of `tokens.dart`.
library;

import 'package:flutter/material.dart';

import 'tokens.dart';
import 'typography.dart';

ThemeData buildTheme() {
  // Forest is the only accent, so it is both primary and secondary. Giving
  // Material a second accent to reach for is how a stray colour appears in a
  // widget nobody styled.
  const scheme = ColorScheme.light(
    primary: C.forest,
    onPrimary: C.white,
    secondary: C.forest,
    onSecondary: C.white,
    surface: C.white,
    onSurface: C.ink,
    error: C.rust,
    onError: C.white,
    outline: C.lineStrong,
    outlineVariant: C.line,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: C.paper,
    fontFamily: Fonts.sans,

    textTheme: const TextTheme(
      bodyLarge: T.body,
      bodyMedium: T.body,
      bodySmall: T.bodySmall,
      labelLarge: T.label,
      labelSmall: T.caption,
    ),

    appBarTheme: const AppBarTheme(
      backgroundColor: C.paper,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      iconTheme: IconThemeData(color: C.ink),
      titleTextStyle: TextStyle(
        fontFamily: Fonts.sans,
        fontSize: 17,
        fontWeight: FontWeight.w500,
        color: C.ink,
      ),
    ),

    // Inputs use lineStrong, not line: the boundary of an interactive control
    // has to clear 3:1 under WCAG 1.4.11, and line measures 1.29:1.
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: C.paper,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: Space.md,
        vertical: 14,
      ),
      border: OutlineInputBorder(
        borderRadius: Radii.controlAll,
        borderSide: const BorderSide(color: C.lineStrong),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: Radii.controlAll,
        borderSide: const BorderSide(color: C.lineStrong),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: Radii.controlAll,
        borderSide: const BorderSide(color: C.forest, width: 1.5),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: Radii.controlAll,
        borderSide: const BorderSide(color: C.rust),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: Radii.controlAll,
        borderSide: const BorderSide(color: C.rust, width: 1.5),
      ),
      labelStyle: T.caption,
      hintStyle: T.bodySmall,
      errorStyle: const TextStyle(
        fontFamily: Fonts.sans,
        fontSize: 13,
        color: C.rust,
      ),
    ),

    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: C.forest,
        foregroundColor: C.white,
        disabledBackgroundColor: C.lineStrong,
        disabledForegroundColor: C.white,
        minimumSize: const Size.fromHeight(48),
        shape: const RoundedRectangleBorder(borderRadius: Radii.controlAll),
        textStyle: const TextStyle(
          fontFamily: Fonts.sans,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
    ),

    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: C.forest,
        textStyle: const TextStyle(
          fontFamily: Fonts.sans,
          fontSize: 14,
          fontWeight: FontWeight.w500,
        ),
      ),
    ),

    dividerTheme: const DividerThemeData(
      color: C.line,
      thickness: 1,
      space: 1,
    ),

    cardTheme: const CardThemeData(
      color: C.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: Radii.cardAll,
        side: BorderSide(color: C.line),
      ),
    ),

    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: C.amber,
      linearTrackColor: C.line,
    ),

    snackBarTheme: const SnackBarThemeData(
      backgroundColor: C.ink,
      contentTextStyle: TextStyle(
        fontFamily: Fonts.sans,
        fontSize: 14,
        color: C.white,
      ),
      behavior: SnackBarBehavior.floating,
    ),
  );
}
