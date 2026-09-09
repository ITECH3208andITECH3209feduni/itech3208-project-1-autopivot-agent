/// Shared pieces every screen draws from.
///
/// The web client has an equivalent file for the same reason: without one, each
/// screen grows its own slightly different card, and the product stops looking
/// like one product. Nothing here declares a colour or a size — see
/// `design/tokens.dart`.
library;

import 'package:flutter/material.dart';

import '../design/tokens.dart';
import '../design/typography.dart';

/// A white surface with the two-layer shadow from the design system.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding});

  final Widget child;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding ?? const EdgeInsets.all(Space.lg),
      decoration: BoxDecoration(
        color: C.white,
        borderRadius: Radii.cardAll,
        border: Border.all(color: C.line),
        boxShadow: cardShadow,
      ),
      child: child,
    );
  }
}

/// An error the user needs to read.
///
/// `liveRegion` is the mobile equivalent of the web client's `role="alert"`:
/// without it a screen reader announces nothing when a sign-in fails, and the
/// user is left with a form that simply did not proceed.
class AppErrorBanner extends StatelessWidget {
  const AppErrorBanner(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(
          horizontal: Space.md,
          vertical: 12,
        ),
        decoration: BoxDecoration(
          color: C.rustTint,
          borderRadius: Radii.controlAll,
        ),
        child: Text(
          message,
          style: const TextStyle(
            fontFamily: Fonts.sans,
            fontSize: 14,
            height: 1.5,
            color: C.rust,
          ),
        ),
      ),
    );
  }
}

/// Where a vehicle's photographs are in the pipeline.
///
/// Four states, and no success colour. Completion is shown by the processed
/// photograph appearing, not by turning a label green — a rule from the brand
/// guidelines that the web client also follows.
enum ProcessingState {
  pending,
  processing,
  complete,
  needsReview;

  static ProcessingState parse(String raw) => switch (raw) {
    'processing' => ProcessingState.processing,
    'complete' => ProcessingState.complete,
    'needs_review' => ProcessingState.needsReview,
    _ => ProcessingState.pending,
  };

  String get label => switch (this) {
    ProcessingState.pending => 'Pending',
    ProcessingState.processing => 'Processing',
    ProcessingState.complete => 'Complete',
    ProcessingState.needsReview => 'Needs review',
  };
}

class StatusPill extends StatelessWidget {
  const StatusPill(this.state, {super.key});

  final ProcessingState state;

  @override
  Widget build(BuildContext context) {
    // amberText rather than amber for the label: plain amber on amberTint is
    // 3.12:1, which fails for text. The darker variant reaches 4.60:1.
    final (background, foreground) = switch (state) {
      ProcessingState.processing => (C.amberTint, C.amberText),
      ProcessingState.needsReview => (C.rustTint, C.rust),
      ProcessingState.complete => (C.forestTint, C.forest),
      ProcessingState.pending => (C.bone, C.inkSoft),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: background,
        borderRadius: const BorderRadius.all(Radius.circular(999)),
      ),
      child: Text(
        state.label,
        style: TextStyle(
          fontFamily: Fonts.sans,
          fontSize: 12,
          fontWeight: FontWeight.w500,
          color: foreground,
        ),
      ),
    );
  }
}

/// A screen that is doing nothing yet, or has nothing to show.
///
/// Written as a statement rather than an apology — a dealership genuinely
/// starts with no vehicles, and that is not an error.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    required this.body,
    this.action,
  });

  final String title;
  final String body;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(title, style: serif(24), textAlign: TextAlign.center),
            const SizedBox(height: Space.sm),
            Text(body, style: T.bodySmall, textAlign: TextAlign.center),
            if (action != null) ...[
              const SizedBox(height: Space.lg),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}
