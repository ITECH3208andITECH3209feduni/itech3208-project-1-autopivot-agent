/// App preferences: biometric lock, haptic feedback, and a way back into
/// the welcome tour. Reached from the account sheet's own Settings row —
/// every signed-in role gets this one, unlike Team or Dealerships, which
/// are administration for exactly one role each and happen to share the
/// same sheet.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../settings/app_preferences.dart';
import '../../settings/biometric_auth.dart';
import '../../widgets/primitives.dart';
import 'welcome_tour_screen.dart';

class AppSettingsScreen extends ConsumerStatefulWidget {
  const AppSettingsScreen({super.key});

  @override
  ConsumerState<AppSettingsScreen> createState() => _AppSettingsScreenState();
}

class _AppSettingsScreenState extends ConsumerState<AppSettingsScreen> {
  bool _checkingBiometrics = false;
  String? _biometricError;

  /// Turning the toggle on is only ever recorded once a real prompt has
  /// actually succeeded — proving the mechanism works before relying on it,
  /// rather than trusting a device report that can go stale (biometrics
  /// removed mid-session, a simulator with none at all) and locking someone
  /// out on the very next launch.
  Future<void> _setBiometricLock(bool value) async {
    setState(() => _biometricError = null);

    if (!value) {
      await ref
          .read(appPreferencesProvider.notifier)
          .setBiometricLockEnabled(false);
      return;
    }

    setState(() => _checkingBiometrics = true);
    final supported = await deviceSupportsAuthentication();
    if (!supported) {
      if (!mounted) return;
      setState(() {
        _checkingBiometrics = false;
        _biometricError =
            'This device has no Face ID, fingerprint or passcode set up, '
            'so there is nothing for AutoPivot to check against.';
      });
      return;
    }

    final confirmed = await authenticate();
    if (!mounted) return;
    setState(() => _checkingBiometrics = false);
    if (!confirmed) {
      setState(
        () => _biometricError = "That didn't succeed — lock was not turned on.",
      );
      return;
    }
    await ref
        .read(appPreferencesProvider.notifier)
        .setBiometricLockEnabled(true);
  }

  @override
  Widget build(BuildContext context) {
    final prefs = ref.watch(appPreferencesProvider);

    return Scaffold(
      body: SafeArea(
        child: CustomScrollView(
          slivers: [
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(
                Space.sm,
                Space.sm,
                Space.lg,
                Space.md,
              ),
              sliver: SliverToBoxAdapter(child: _header()),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(
                Space.lg,
                0,
                Space.lg,
                Space.xl,
              ),
              sliver: SliverToBoxAdapter(
                child: prefs.loaded
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('SECURITY', style: T.caption),
                          const SizedBox(height: Space.sm),
                          _SettingsToggleRow(
                            icon: Icons.fingerprint,
                            title: 'Biometric lock',
                            subtitle:
                                'Require Face ID, fingerprint or your device '
                                'passcode to open AutoPivot.',
                            value: prefs.biometricLockEnabled,
                            busy: _checkingBiometrics,
                            onChanged: _setBiometricLock,
                          ),
                          if (_biometricError != null) ...[
                            const SizedBox(height: Space.sm),
                            AppErrorBanner(_biometricError!),
                          ],
                          const SizedBox(height: Space.xl),
                          Text('FEEDBACK', style: T.caption),
                          const SizedBox(height: Space.sm),
                          _SettingsToggleRow(
                            icon: Icons.vibration,
                            title: 'Haptic feedback',
                            subtitle:
                                'A light tap when the camera aligns, and on '
                                'other key actions throughout the app.',
                            value: prefs.hapticsEnabled,
                            onChanged: (value) => ref
                                .read(appPreferencesProvider.notifier)
                                .setHapticsEnabled(value),
                          ),
                          const SizedBox(height: Space.xl),
                          Text('HELP', style: T.caption),
                          const SizedBox(height: Space.sm),
                          _SettingsActionRow(
                            icon: Icons.tour_outlined,
                            title: 'Show the welcome tour',
                            subtitle:
                                'A quick look at capturing, reviewing '
                                'and submitting a set.',
                            onTap: () => Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) =>
                                    const WelcomeTourScreen(dismissible: true),
                              ),
                            ),
                          ),
                        ],
                      )
                    : const SizedBox.shrink(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _header() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        IconButton(
          onPressed: () => Navigator.of(context).pop(),
          icon: const Icon(Icons.arrow_back, color: C.inkSoft),
          tooltip: 'Back',
        ),
        const SizedBox(width: Space.xs),
        Padding(
          padding: const EdgeInsets.only(top: Space.sm),
          child: Text('Settings', style: serif(28)),
        ),
      ],
    );
  }
}

class _SettingsToggleRow extends StatelessWidget {
  const _SettingsToggleRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
    this.busy = false,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool value;
  final bool busy;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: C.forest),
          const SizedBox(width: Space.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: T.label),
                const SizedBox(height: 2),
                Text(subtitle, style: T.bodySmall),
              ],
            ),
          ),
          const SizedBox(width: Space.sm),
          busy
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: Padding(
                    padding: EdgeInsets.all(2),
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                )
              : Switch(
                  value: value,
                  activeThumbColor: C.forest,
                  onChanged: onChanged,
                ),
        ],
      ),
    );
  }
}

class _SettingsActionRow extends StatelessWidget {
  const _SettingsActionRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: Material(
        type: MaterialType.transparency,
        borderRadius: Radii.cardAll,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(Space.lg),
            child: Row(
              children: [
                Icon(icon, size: 20, color: C.forest),
                const SizedBox(width: Space.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: T.label),
                      const SizedBox(height: 2),
                      Text(subtitle, style: T.bodySmall),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right, size: 18, color: C.lineStrong),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
