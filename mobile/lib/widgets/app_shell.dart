/// The persistent chrome around every signed-in screen: the dealership name
/// at the top, expanding into account actions on tap, and a floating camera
/// action bottom-right.
///
/// Wraps go_router's `ShellRoute` child — the dealership name and the camera
/// action stay mounted and keep their own state (the account panel's
/// open/closed flag) as the user moves between screens inside the shell;
/// only the content below the header changes. Sign-in and the forced
/// password change sit outside this shell entirely and are unaffected — a
/// screen the user is not meant to leave has no business showing a sign-out
/// button.
///
/// Camera and settings are both screens this app grows into later, not
/// today. What exists here is the shape they will slot into: a bubble that
/// currently says so rather than doing nothing when pressed, and an account
/// panel with a "Settings" entry that is visibly, honestly not live yet
/// rather than a dead tap.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_controller.dart';
import '../design/tokens.dart';
import '../design/typography.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  bool _accountOpen = false;

  void _toggleAccount() => setState(() => _accountOpen = !_accountOpen);

  void _signOut() {
    setState(() => _accountOpen = false);
    ref.read(authProvider.notifier).signOut();
  }

  void _cameraComingSoon() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Camera capture is coming in a later update.')),
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
                open: _accountOpen,
                onToggle: _toggleAccount,
                onSignOut: _signOut,
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
      floatingActionButton: _CameraBubble(onPressed: _cameraComingSoon),
    );
  }
}

/// The dealership name, a chevron, and — expanded — account actions.
///
/// An inline expansion rather than a popup menu: the brief asked for the
/// panel to appear where the name is, not detached from it in a menu that
/// could open anywhere Flutter decides has room.
class _AccountHeader extends StatelessWidget {
  const _AccountHeader({
    required this.dealershipName,
    required this.open,
    required this.onToggle,
    required this.onSignOut,
  });

  final String dealershipName;
  final bool open;
  final VoidCallback onToggle;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Material(
          type: MaterialType.transparency,
          child: InkWell(
            onTap: onToggle,
            borderRadius: Radii.controlAll,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: Space.xs),
              child: Semantics(
                button: true,
                label: open
                    ? 'Account menu, expanded'
                    : 'Account menu, collapsed',
                excludeSemantics: true,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(dealershipName, style: T.label),
                    const SizedBox(width: Space.xs),
                    AnimatedRotation(
                      turns: open ? 0.5 : 0,
                      duration: const Duration(milliseconds: 150),
                      child: const Icon(
                        Icons.keyboard_arrow_down,
                        size: 18,
                        color: C.inkSoft,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
          alignment: Alignment.topLeft,
          child: open
              ? Padding(
                  padding: const EdgeInsets.only(top: Space.sm),
                  child: _AccountPanel(onSignOut: onSignOut),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

class _AccountPanel extends StatelessWidget {
  const _AccountPanel({required this.onSignOut});

  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: C.white,
        borderRadius: Radii.cardAll,
        border: Border.all(color: C.line),
        boxShadow: cardShadow,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Present and visibly inert, rather than absent — the brief is
          // explicit that this app should already show the shape settings
          // will slot into, not pretend the account panel only ever has one
          // item in it.
          const _AccountPanelRow(
            icon: Icons.settings_outlined,
            label: 'Settings',
            trailing: 'Coming soon',
            onTap: null,
          ),
          const Divider(height: 1, color: C.line),
          _AccountPanelRow(
            icon: Icons.logout,
            label: 'Sign out',
            onTap: onSignOut,
          ),
        ],
      ),
    );
  }
}

class _AccountPanelRow extends StatelessWidget {
  const _AccountPanelRow({
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
          padding: const EdgeInsets.symmetric(
            horizontal: Space.md,
            vertical: 12,
          ),
          child: Row(
            children: [
              Icon(icon, size: 18, color: contentColor),
              const SizedBox(width: Space.sm),
              Expanded(
                child: Text(
                  label,
                  style: T.body.copyWith(fontSize: 14, color: contentColor),
                ),
              ),
              if (trailing != null)
                Text(trailing!, style: T.caption),
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
class _CameraBubble extends StatelessWidget {
  const _CameraBubble({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return FloatingActionButton(
      onPressed: onPressed,
      backgroundColor: C.forest,
      foregroundColor: C.white,
      tooltip: 'Add photographs (coming soon)',
      child: const Icon(Icons.camera_alt_outlined),
    );
  }
}
