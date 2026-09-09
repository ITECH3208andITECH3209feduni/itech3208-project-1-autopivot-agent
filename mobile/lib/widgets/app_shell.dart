/// The persistent chrome around every signed-in screen: an avatar bubble and
/// dealership name at the top, opening an iOS-style sheet with account
/// actions, and a floating camera action bottom-right.
///
/// Wraps go_router's `ShellRoute` child — the header and the camera action
/// stay mounted and keep their own state as the user moves between screens
/// inside the shell; only the content below the header changes. Sign-in and
/// the forced password change sit outside this shell entirely and are
/// unaffected — a screen the user is not meant to leave has no business
/// showing a sign-out button.
///
/// The account sheet slides up from the bottom with a drag handle and rounded
/// top corners — the same shape iOS uses for its own sheets, and the one an
/// app like Flighty uses for its account panel — rather than expanding
/// in place under the header. A sheet gives the same information room to
/// breathe (dealership, the signed-in person, then actions) without pushing
/// the page content down every time it opens.
///
/// The camera bubble opens the real capture screen at [AppRoutes.capture].
/// Settings is not built yet — its row in the sheet says so plainly rather
/// than being a dead tap.
library;

import 'package:animations/animations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models/user.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/typography.dart';
import '../features/capture/capture_screen.dart';

/// The initials shown in the header's avatar bubble.
///
/// Falls back to 'A' for AutoPivot when there is no signed-in user yet (the
/// shell can render for one frame before [currentUserProvider] settles) or
/// when a name is somehow empty — never an empty bubble.
String _initials(User? user) {
  if (user == null) return 'A';
  final first = user.firstName.isNotEmpty ? user.firstName[0] : '';
  final last = user.lastName.isNotEmpty ? user.lastName[0] : '';
  final initials = ('$first$last').toUpperCase();
  return initials.isNotEmpty ? initials : 'A';
}

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  void _signOut() => ref.read(authProvider.notifier).signOut();

  void _openAccountSheet(User? user) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: C.paper,
      showDragHandle: true,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(Radii.card)),
      ),
      builder: (context) => _AccountSheet(user: user, onSignOut: _signOut),
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(currentUserProvider);
    final dealershipName = user?.dealership?.name ?? 'AutoPivot';

    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                Space.lg,
                Space.md,
                Space.lg,
                0,
              ),
              child: _AccountHeader(
                dealershipName: dealershipName,
                initials: _initials(user),
                onTap: () => _openAccountSheet(user),
              ),
            ),
            // The routed screen. Each one keeps its own Scaffold — this
            // outer one exists for the header and the camera action, not to
            // replace what each screen already provides for its own content
            // and, where relevant, its own way back.
            Expanded(child: widget.child),
          ],
        ),
      ),
      floatingActionButton: const _CameraBubble(),
    );
  }
}

/// The avatar bubble, dealership name and a chevron hinting there is more
/// underneath. The whole row is one tap target, opening the account sheet.
class _AccountHeader extends StatelessWidget {
  const _AccountHeader({
    required this.dealershipName,
    required this.initials,
    required this.onTap,
  });

  final String dealershipName;
  final String initials;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      type: MaterialType.transparency,
      child: InkWell(
        onTap: onTap,
        borderRadius: Radii.controlAll,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: Space.xs),
          child: Semantics(
            button: true,
            label: 'Account and settings',
            excludeSemantics: true,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _AvatarBubble(initials: initials),
                const SizedBox(width: Space.sm),
                Text(dealershipName, style: T.label),
                const SizedBox(width: Space.xs),
                const Icon(
                  Icons.keyboard_arrow_down,
                  size: 18,
                  color: C.inkSoft,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A small circle carrying the signed-in person's initials — the "bubble"
/// that makes the header read as an account entry point rather than plain
/// text, the way an avatar does in most apps that use this sheet pattern.
class _AvatarBubble extends StatelessWidget {
  const _AvatarBubble({required this.initials});

  final String initials;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 28,
      height: 28,
      alignment: Alignment.center,
      decoration: const BoxDecoration(
        color: C.forestTint,
        shape: BoxShape.circle,
      ),
      child: Text(
        initials,
        style: T.body.copyWith(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: C.forest,
        ),
      ),
    );
  }
}

/// The sheet's content: who this dealership and person are, then what can be
/// done — Settings (not yet live) and Sign out.
class _AccountSheet extends StatelessWidget {
  const _AccountSheet({required this.user, required this.onSignOut});

  final User? user;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final dealership = user?.dealership;
    final dealershipName = dealership?.name ?? 'AutoPivot';
    final location = dealership?.location;
    final hasLocation = location != null && location.isNotEmpty;

    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Space.lg, Space.sm, Space.lg, Space.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(dealershipName, style: serif(28)),
            if (hasLocation) ...[
              const SizedBox(height: Space.xs),
              Text(location, style: T.bodySmall),
            ],
            if (user != null) ...[
              const SizedBox(height: Space.lg),
              Text(user!.displayName, style: T.label),
              const SizedBox(height: 2),
              Text(user!.email, style: T.bodySmall),
            ],
            const SizedBox(height: Space.lg),
            const Divider(height: 1, color: C.line),
            const _AccountSheetRow(
              icon: Icons.settings_outlined,
              label: 'Settings',
              trailing: 'Coming soon',
              onTap: null,
            ),
            const Divider(height: 1, color: C.line),
            _AccountSheetRow(
              icon: Icons.logout,
              label: 'Sign out',
              // Pop the sheet first, then sign out — signing out while the
              // sheet is still on screen would leave it showing an account
              // that no longer exists in AuthState for the instant before
              // the router redirect fires.
              onTap: () {
                Navigator.of(context).pop();
                onSignOut();
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _AccountSheetRow extends StatelessWidget {
  const _AccountSheetRow({
    required this.icon,
    required this.label,
    required this.onTap,
    this.trailing,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final String? trailing;

  bool get _enabled => onTap != null;

  @override
  Widget build(BuildContext context) {
    final contentColor = _enabled ? C.ink : C.inkSoft;

    return Material(
      type: MaterialType.transparency,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14),
          child: Row(
            children: [
              Icon(icon, size: 18, color: contentColor),
              const SizedBox(width: Space.sm),
              Expanded(
                child: Text(
                  label,
                  style: T.body.copyWith(fontSize: 15, color: contentColor),
                ),
              ),
              if (trailing != null) Text(trailing!, style: T.caption),
            ],
          ),
        ),
      ),
    );
  }
}

/// The camera entry point — a floating bubble rather than a bottom-bar tab.
///
/// Chosen over a conventional tab specifically because a customised camera
/// surface is the reason this app is Flutter rather than a hybrid wrapper in
/// the first place (see docs/MOBILE_PLAN.md) — the entry point to it reads as
/// its own deliberate action, not one icon among three.
///
/// [OpenContainer] is Material's "container transform" pattern: the bubble
/// itself grows to fill the screen and become [CaptureScreen], rather than
/// the capture screen sliding in as an unrelated route — and shrinks back
/// into the bubble on the way out, via the `closeContainer` callback passed
/// as [CaptureScreen.onClose]. This is why capture has no go_router route of
/// its own: the transform owns its own push, and giving it a second, plainer
/// entry point would mean two different ways to arrive with two different
/// closing animations.
class _CameraBubble extends StatelessWidget {
  const _CameraBubble();

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: 'Add photographs',
      child: OpenContainer(
        transitionDuration: const Duration(milliseconds: 350),
        transitionType: ContainerTransitionType.fade,
        closedShape: const CircleBorder(),
        closedElevation: 6,
        closedColor: C.forest,
        openColor: Colors.black,
        closedBuilder: (context, openContainer) => SizedBox(
          width: 56,
          height: 56,
          child: Semantics(
            button: true,
            label: 'Add photographs',
            excludeSemantics: true,
            child: Icon(Icons.camera_alt_outlined, color: C.white),
          ),
        ),
        openBuilder: (context, closeContainer) =>
            CaptureScreen(onClose: closeContainer),
      ),
    );
  }
}
