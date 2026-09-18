/// A standing developer tool. Two jobs:
///
///   - Preview a screen with canned data, no backend needed.
///   - Point the real app at any backend URL and sign in for real, without
///     rebuilding to change it. A RunPod tunnel URL changes every time the
///     tunnel restarts (see docs/DEMO_RUNBOOK.md) — pasting a new one here
///     costs nothing, where `--dart-define=API_BASE_URL=...` costs a rebuild.
///
/// Never reachable from a production build: `main.dart` does not import
/// anything under `lib/dev/`, so nothing here exists unless this file is
/// explicitly used as the build's entrypoint —
///
///     flutter run -t lib/main_dev.dart
///
/// One thing worth knowing before using this on a device that has also run
/// the real app: both share the same bundle id, so they can share the same
/// Keychain entry. Signing in for real here can leave a token the real app
/// then also picks up, and vice versa. Harmless for a single developer on a
/// simulator, worth remembering on a shared device.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../app.dart';
import '../auth/auth_controller.dart';
import '../bootstrap.dart';
import '../design/theme.dart';
import '../design/tokens.dart';
import '../design/typography.dart';
import 'fixtures.dart';

class DevToolsApp extends StatelessWidget {
  const DevToolsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AutoPivot — Dev Tools',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const _DevToolsHome(),
    );
  }
}

class _DevToolsHome extends StatefulWidget {
  const _DevToolsHome();

  @override
  State<_DevToolsHome> createState() => _DevToolsHomeState();
}

class _DevToolsHomeState extends State<_DevToolsHome> {
  // Pre-filled with the same default the real app would resolve to, so
  // there is something sensible to look at before a RunPod URL is pasted
  // over it.
  late final _urlController = TextEditingController(text: defaultBaseUrl());

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  /// Pushes a full [AutoPivotApp] fixed to [state], optionally with [api]
  /// standing in for the network. Deliberately not wrapped in
  /// [AppBootstrap] — see the warning on [FixedAuthController].
  void _openPreview(AuthState state, {ApiClient? api}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ProviderScope(
          overrides: [
            authProvider.overrideWith(() => FixedAuthController(state)),
            if (api != null) apiClientProvider.overrideWithValue(api),
          ],
          child: const AutoPivotApp(),
        ),
      ),
    );
  }

  /// Pushes the real, unmodified app — real [AuthController], real secure
  /// storage — pointed at whatever base URL is in the field. Wrapped in
  /// [AppBootstrap] because this path needs the real `restore()` call the
  /// real app makes at cold start: without it, the router would sit on
  /// [AuthChecking] forever, since nothing else would ever call it.
  void _connect() {
    final url = _cleanBaseUrl(_urlController.text);
    if (url.isEmpty) return;

    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(ApiClient(baseUrl: url)),
          ],
          child: const AppBootstrap(child: AutoPivotApp()),
        ),
      ),
    );
  }

  String _cleanBaseUrl(String raw) {
    final trimmed = raw.trim();
    return trimmed.endsWith('/')
        ? trimmed.substring(0, trimmed.length - 1)
        : trimmed;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: C.paper,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(Space.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Dev Tools', style: serif(32)),
              const SizedBox(height: Space.xs),
              Text(
                'Not part of what a dealer sees. For previewing a screen '
                'without a backend, and for pointing the real app at one.',
                style: T.bodySmall,
              ),
              const SizedBox(height: Space.xl),

              Text('PREVIEWS — sample data, no network', style: T.caption),
              const SizedBox(height: Space.sm),
              _DevButton(
                label: 'Sign-in screen',
                onTap: () => _openPreview(const AuthSignedOut()),
              ),
              const SizedBox(height: Space.sm),
              _DevButton(
                label: 'Forced change-password screen',
                onTap: () => _openPreview(
                  AuthSignedIn(sampleUser(mustChangePassword: true)),
                ),
              ),
              const SizedBox(height: Space.sm),
              _DevButton(
                label: 'Listings screen — sample vehicles',
                onTap: () => _openPreview(
                  AuthSignedIn(sampleUser()),
                  api: FakeApiClient(),
                ),
              ),

              const SizedBox(height: Space.xl),
              Text('REAL BACKEND', style: T.caption),
              const SizedBox(height: Space.sm),
              Text(
                'Paste a base URL and sign in for real. For a RunPod pod, '
                'bash scripts/runpod_up.sh --status prints its current '
                'tunnel URL.',
                style: T.bodySmall,
              ),
              const SizedBox(height: Space.sm),
              TextField(
                controller: _urlController,
                keyboardType: TextInputType.url,
                autocorrect: false,
                textCapitalization: TextCapitalization.none,
                decoration: const InputDecoration(
                  labelText: 'Base URL',
                  hintText: 'https://xxxx.trycloudflare.com',
                ),
              ),
              const SizedBox(height: Space.md),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _connect,
                  child: const Text('Connect and sign in'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DevButton extends StatelessWidget {
  const _DevButton({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: OutlinedButton(
        onPressed: onTap,
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(
            horizontal: Space.md,
            vertical: 14,
          ),
          side: const BorderSide(color: C.lineStrong),
          shape: const RoundedRectangleBorder(borderRadius: Radii.controlAll),
          alignment: Alignment.centerLeft,
        ),
        child: Text(label, style: T.label),
      ),
    );
  }
}
