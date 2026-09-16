/// A short, swipeable walkthrough of the everyday loop — capture, review,
/// submit, track — shown automatically the first time a new account signs
/// in (see `app.dart`'s builder), and replayable any time from Settings.
///
/// Four pages, not a video or a longer tour: a photographer's first session
/// is spent standing at a car, and the thing worth teaching in thirty
/// seconds is what each screen is for, not every control on it.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../settings/app_preferences.dart';

class _TourPage {
  const _TourPage({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;
}

const _pages = [
  _TourPage(
    icon: Icons.center_focus_strong_outlined,
    title: 'One angle at a time',
    body:
        'Tap the camera button and AutoPivot guides you through all eight '
        "angles — a silhouette shows where the car should sit, and the "
        'level indicator turns green when the shot is lined up.',
  ),
  _TourPage(
    icon: Icons.grid_view_outlined,
    title: 'Review before you leave',
    body:
        'Once every angle is shot, look over the set. Tap any photo to '
        'retake or drop it — the vehicle stays in front of you until '
        "you're happy, not after.",
  ),
  _TourPage(
    icon: Icons.auto_awesome_outlined,
    title: 'Submit starts processing',
    body:
        'Add the make, model and year, pick a backdrop, and submit — the '
        'pipeline starts right away instead of waiting for someone to '
        'kick it off on the platform later.',
  ),
  _TourPage(
    icon: Icons.compare_outlined,
    title: 'Track it from anywhere',
    body:
        'A banner up top shows how many vehicles are still processing, '
        'wherever you are in the app. Once done, drag across a photo on '
        "its listing to compare the original against the result.",
  ),
];

/// Shows [WelcomeTourScreen] automatically in place of [child] for an
/// account that has never seen it, and finishing or skipping is what
/// records that — wired into `app.dart`'s builder for a signed-in session
/// that has already completed its forced password change, the same
/// ordering reason `AppLockGate` sits where it does: nothing here should
/// compete with a screen the user cannot yet leave.
class WelcomeTourGate extends ConsumerWidget {
  const WelcomeTourGate({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final prefs = ref.watch(appPreferencesProvider);
    if (!prefs.loaded || prefs.welcomeTourSeen) return child;
    return const WelcomeTourScreen(dismissible: false);
  }
}

class WelcomeTourScreen extends ConsumerStatefulWidget {
  const WelcomeTourScreen({super.key, required this.dismissible});

  /// True when reached from Settings — shows a close button and never
  /// touches [AppPreferences.welcomeTourSeen], since a replay is not the
  /// event that flag exists to record. False for the automatic first-run
  /// showing, where finishing (or skipping) is what marks it seen.
  final bool dismissible;

  @override
  ConsumerState<WelcomeTourScreen> createState() => _WelcomeTourScreenState();
}

class _WelcomeTourScreenState extends ConsumerState<WelcomeTourScreen> {
  final _controller = PageController();
  int _page = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _finish() {
    if (!widget.dismissible) {
      ref.read(appPreferencesProvider.notifier).setWelcomeTourSeen(true);
    }
    Navigator.of(context).pop();
  }

  void _next() {
    if (_page == _pages.length - 1) {
      _finish();
      return;
    }
    _controller.nextPage(
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    final isLast = _page == _pages.length - 1;

    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  Space.lg,
                  Space.sm,
                  Space.md,
                  0,
                ),
                child: TextButton(
                  onPressed: _finish,
                  child: Text(widget.dismissible ? 'Close' : 'Skip'),
                ),
              ),
            ),
            Expanded(
              child: PageView.builder(
                controller: _controller,
                itemCount: _pages.length,
                onPageChanged: (page) => setState(() => _page = page),
                itemBuilder: (context, index) => _PageContent(_pages[index]),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                Space.xl,
                0,
                Space.xl,
                Space.xl,
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (var i = 0; i < _pages.length; i++)
                        AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          margin: const EdgeInsets.symmetric(horizontal: 3),
                          width: i == _page ? 18 : 6,
                          height: 6,
                          decoration: BoxDecoration(
                            color: i == _page ? C.forest : C.line,
                            borderRadius: Radii.controlAll,
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: Space.lg),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _next,
                      child: Text(isLast ? "Let's go" : 'Next'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PageContent extends StatelessWidget {
  const _PageContent(this.page);

  final _TourPage page;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: Space.xl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 88,
            height: 88,
            decoration: const BoxDecoration(
              color: C.forestTint,
              shape: BoxShape.circle,
            ),
            child: Icon(page.icon, size: 36, color: C.forest),
          ),
          const SizedBox(height: Space.xl),
          Text(
            page.title,
            style: serif(26),
            textAlign: TextAlign.center,
            textWidthBasis: TextWidthBasis.longestLine,
          ),
          const SizedBox(height: Space.sm),
          Text(
            page.body,
            style: T.body.copyWith(color: C.inkSoft),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}
