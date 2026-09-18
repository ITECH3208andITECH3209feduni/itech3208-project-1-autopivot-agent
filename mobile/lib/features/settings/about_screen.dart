/// What build this is, and where it is pointed — the screen support asks a
/// dealer to open before anything else.
///
/// Until this existed there was no way to answer "which version are you
/// running?" from inside the app at all. A dealer cannot read a version out
/// of an App Store listing (this is not distributed through one yet), and a
/// build number read aloud over the phone is transcribed wrong often enough
/// to be worth removing from the loop entirely — hence [_copyDiagnostics],
/// which puts everything support needs on the clipboard in one tap.
///
/// The API endpoint is on this screen for a specific reason rather than for
/// completeness. The single most common misconfiguration in this project so
/// far is an app pointed at the wrong host — a device build still carrying a
/// developer's LAN address, or an Android build reaching for the emulator's
/// `10.0.2.2` on real hardware — and from the user's side that is
/// indistinguishable from the server being down. Both produce a sign-in that
/// times out. Showing the address someone is actually talking to turns a
/// support conversation that starts with "is it broken?" into one that starts
/// with "it is pointed at the wrong place."
///
/// [buildRef] is a git commit, supplied at build time rather than read at
/// runtime: a release build has no repository to inspect, so the value has to
/// be baked in by whoever produced the artefact —
///
///     flutter build apk --dart-define=BUILD_REF=$(git rev-parse --short HEAD)
///
/// A plain `flutter run` supplies nothing and the screen says so rather than
/// showing an empty row, because "local build" is a true and useful answer
/// while a blank space is neither.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/primitives.dart';

/// The commit this build was cut from, or empty on a build that was not told.
const buildRef = String.fromEnvironment('BUILD_REF');

/// Read once per app session. The bundle's version cannot change while the
/// app is running, so there is nothing to invalidate and no reason to hit the
/// platform channel again on every visit.
final _packageInfoProvider = FutureProvider<PackageInfo>(
  (ref) => PackageInfo.fromPlatform(),
);

class AboutScreen extends ConsumerWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final info = ref.watch(_packageInfoProvider);
    final endpoint = ref.read(apiClientProvider).baseUrl;

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
              sliver: SliverToBoxAdapter(child: _header(context)),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(
                Space.lg,
                0,
                Space.lg,
                Space.xl,
              ),
              sliver: SliverToBoxAdapter(
                child: info.when(
                  loading: () => const SizedBox.shrink(),
                  // A platform channel that fails still leaves the endpoint and
                  // the build reference worth showing, so the screen degrades
                  // to what it does know rather than to an error page.
                  error: (_, _) => _Body(
                    version: null,
                    buildNumber: null,
                    endpoint: endpoint,
                  ),
                  data: (data) => _Body(
                    version: data.version,
                    buildNumber: data.buildNumber,
                    endpoint: endpoint,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context) {
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
          child: Text('About', style: serif(28)),
        ),
      ],
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({
    required this.version,
    required this.buildNumber,
    required this.endpoint,
  });

  final String? version;
  final String? buildNumber;
  final String endpoint;

  String get _versionLine {
    if (version == null) return 'Unavailable';
    return buildNumber == null ? version! : '$version ($buildNumber)';
  }

  String get _buildRefLine => buildRef.isEmpty ? 'Local build' : buildRef;

  String get _platformLine =>
      '${Platform.operatingSystem} ${Platform.operatingSystemVersion}';

  /// One block of text carrying everything a support conversation needs, so
  /// the dealer pastes rather than reads it out.
  String get _diagnostics => [
    'AutoPivot',
    'Version: $_versionLine',
    'Build: $_buildRefLine',
    'Endpoint: $endpoint',
    'Platform: $_platformLine',
  ].join('\n');

  Future<void> _copyDiagnostics(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: _diagnostics));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Details copied — paste them to support.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('THIS BUILD', style: T.caption),
        const SizedBox(height: Space.sm),
        AppCard(
          child: Column(
            children: [
              _DetailRow(label: 'Version', value: _versionLine),
              const _RowDivider(),
              _DetailRow(label: 'Build', value: _buildRefLine),
              const _RowDivider(),
              _DetailRow(label: 'Platform', value: _platformLine),
            ],
          ),
        ),
        const SizedBox(height: Space.xl),
        Text('CONNECTION', style: T.caption),
        const SizedBox(height: Space.sm),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DetailRow(label: 'Endpoint', value: endpoint),
              const SizedBox(height: Space.sm),
              Text(
                'Where this app sends everything. If sign-in keeps timing '
                'out, check this is the address you expect before assuming '
                'the server is down.',
                style: T.bodySmall,
              ),
            ],
          ),
        ),
        const SizedBox(height: Space.xl),
        FilledButton.icon(
          onPressed: () => _copyDiagnostics(context),
          icon: const Icon(Icons.copy_all_outlined, size: 18),
          label: const Text('Copy details for support'),
        ),
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(width: 92, child: Text(label, style: T.label)),
        const SizedBox(width: Space.sm),
        // Endpoints and OS strings are both long enough to wrap on a phone,
        // and a clipped one is worse than useless on a screen whose whole
        // job is reporting exact values.
        Expanded(
          child: Text(
            value,
            style: T.bodySmall,
            softWrap: true,
          ),
        ),
      ],
    );
  }
}

class _RowDivider extends StatelessWidget {
  const _RowDivider();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: Space.sm),
      child: Divider(height: 1, thickness: 1, color: C.line),
    );
  }
}
