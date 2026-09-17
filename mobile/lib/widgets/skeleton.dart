/// Loading placeholders shaped like the content they stand in for, with a
/// soft highlight sweeping across them — the "feels faster" half of a load:
/// a spinner says "wait"; a shape the size of the coming title, pill and
/// photo says "here", before any of it has actually arrived.
///
/// One [ShimmerGroup] per loading body, wrapping as many [SkeletonBox]es as
/// that body needs. A single [AnimationController] drives every box inside
/// it — not one controller per box, which would mean eight tickers running
/// for an eight-row list — shared down through [_ShimmerScope], an
/// [InheritedWidget] rather than a constructor parameter threaded through
/// every intermediate widget.
///
/// Respects reduced motion: when the platform asks for it
/// ([MediaQueryData.disableAnimations]), the group never starts its
/// controller and every box renders as a flat, static tone instead of
/// sweeping — the shape still communicates "loading", the motion itself is
/// what reduced motion is asking to not have.
library;

import 'package:flutter/material.dart';

import '../design/tokens.dart';
import 'primitives.dart';

class ShimmerGroup extends StatefulWidget {
  const ShimmerGroup({super.key, required this.child});

  final Widget child;

  @override
  State<ShimmerGroup> createState() => _ShimmerGroupState();
}

class _ShimmerGroupState extends State<ShimmerGroup>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    );
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // MediaQuery isn't available yet in initState (the widget isn't attached
    // to the tree), so the reduced-motion check lives here instead — also
    // covers the OS setting flipping while this screen is already open.
    final reduceMotion = MediaQuery.of(context).disableAnimations;
    if (reduceMotion) {
      if (_controller.isAnimating) _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.of(context).disableAnimations;
    return _ShimmerScope(
      animation: reduceMotion ? null : _controller,
      child: widget.child,
    );
  }
}

class _ShimmerScope extends InheritedWidget {
  const _ShimmerScope({required this.animation, required super.child});

  /// Null under reduced motion — every [SkeletonBox] reading this renders
  /// its static frame instead of subscribing to a running animation.
  final Animation<double>? animation;

  static Animation<double>? of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<_ShimmerScope>()?.animation;

  @override
  bool updateShouldNotify(_ShimmerScope oldWidget) =>
      animation != oldWidget.animation;
}

/// One placeholder shape. Must be built under a [ShimmerGroup] — reads its
/// animation from context rather than owning one, which is the entire point
/// of the group existing.
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({
    super.key,
    this.width,
    this.height,
    this.borderRadius = Radii.controlAll,
  });

  final double? width;
  final double? height;
  final BorderRadius borderRadius;

  @override
  Widget build(BuildContext context) {
    final animation = _ShimmerScope.of(context);
    if (animation == null) {
      return _box(alignShift: 0);
    }
    return AnimatedBuilder(
      animation: animation,
      builder: (context, _) => _box(alignShift: (animation.value * 3) - 1.5),
    );
  }

  Widget _box({required double alignShift}) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: borderRadius,
        gradient: LinearGradient(
          begin: Alignment(alignShift - 0.6, 0),
          end: Alignment(alignShift + 0.6, 0),
          colors: const [C.bone, C.line, C.bone],
        ),
      ),
    );
  }
}

/// A skeleton row shaped like [AppCard] — the shell most list rows in this
/// app already share, so a loading list reads as "the same list, not yet
/// filled in" rather than a different, generic loading widget.
class SkeletonCard extends StatelessWidget {
  const SkeletonCard({super.key, required this.lines});

  /// Width fractions (0–1) for each line under the title row, narrowest
  /// last — the same visual taper real text leaves on a card that ends in a
  /// short trailing detail rather than a full-width sentence.
  final List<double> lines;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(Space.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(child: SkeletonBox(height: 16)),
              const SizedBox(width: Space.sm),
              SkeletonBox(
                width: 64,
                height: 20,
                borderRadius: Radii.controlAll,
              ),
            ],
          ),
          const SizedBox(height: Space.sm),
          for (final fraction in lines) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: fraction,
                child: const SkeletonBox(height: 13),
              ),
            ),
            const SizedBox(height: 4),
          ],
        ],
      ),
    );
  }
}
