/// The sign-in screen — the only door into the app.
///
/// There is deliberately nothing else on it. AutoPivot accounts are
/// provisioned for named dealerships rather than self-served, so this screen
/// carries no sign-up link, no "create an account" text and no forgotten-
/// password flow: offering any of those would promise a self-service path
/// that does not exist behind this API.
///
/// The sign-in endpoint also returns an identical 401 for three different
/// causes — unknown email, wrong password, deactivated account — so that it
/// cannot be used to enumerate which email addresses have accounts. This
/// screen must not undo that: it shows whatever message the thrown
/// [ApiException] already carries and never tries to guess which of the
/// three happened.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/primitives.dart';

class SignInScreen extends ConsumerStatefulWidget {
  const SignInScreen({super.key});

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _passwordFocus = FocusNode();

  // Local loading flag rather than reading a submitting state off the auth
  // controller: [AuthController.signIn] only ever settles into
  // [AuthSignedIn] on success, so there is no controller-side "submitting"
  // state to read, and the screen has to track the in-flight request itself.
  bool _submitting = false;

  // Password fields obscure by default; a phone keyboard makes a typo easy
  // and, unlike an email field, there is no visible feedback that one has
  // happened until the sign-in fails.
  bool _obscurePassword = true;

  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    // Both the button and the password field's "done" action call this, and
    // disabling the controls while a request is outstanding does not fully
    // close the gap — a queued key event can still land after the rebuild.
    // The guard is what actually stops a second request going out.
    if (_submitting) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      await ref
          .read(authProvider.notifier)
          .signIn(
            // Trimmed here rather than relying on the controller: a stray
            // leading or trailing space from a mobile keyboard would
            // otherwise read as an unknown email and produce the same
            // deliberately generic failure, which is a confusing thing to
            // debug from the outside.
            email: _emailController.text.trim(),
            password: _passwordController.text,
          );
      // No navigation on success: the router reacts to authProvider settling
      // into AuthSignedIn and redirects on its own. Pushing a route here
      // would race it.
    } on ApiException catch (e) {
      // Every ApiException already carries a message that is safe to show
      // as-is — in particular ApiInvalidCredentialsException's, which is
      // deliberately the same text for a wrong password, an unknown email
      // and a deactivated account. Writing a screen-local copy for that case
      // would risk narrowing it back down to one of the three.
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            // Scrolling rather than a fixed centred column: on a small phone
            // with the keyboard open for the password field, a fixed layout
            // would push the submit button off-screen.
            padding: const EdgeInsets.all(Space.xl),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('AutoPivot', style: serif(36)),
                  const SizedBox(height: Space.sm),
                  Text(
                    'Sign in to your dealership account.',
                    style: T.bodySmall,
                  ),
                  const SizedBox(height: Space.xl),
                  // Placed in the tree only while there is an error, rather
                  // than an always-present banner hidden with Opacity or
                  // Visibility, because AppErrorBanner's live-region
                  // semantics only announce anything to a screen reader when
                  // the widget actually appears.
                  if (_error case final error?) ...[
                    AppErrorBanner(error),
                    const SizedBox(height: Space.md),
                  ],
                  // One AutofillGroup so a phone's password manager treats
                  // the email and password fields as one login form rather
                  // than two unrelated fields — autofillHints alone does not
                  // reliably trigger the save/fill prompt without it.
                  AutofillGroup(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        TextFormField(
                          controller: _emailController,
                          enabled: !_submitting,
                          autofocus: true,
                          keyboardType: TextInputType.emailAddress,
                          textInputAction: TextInputAction.next,
                          textCapitalization: TextCapitalization.none,
                          autocorrect: false,
                          autofillHints: const [
                            AutofillHints.username,
                            AutofillHints.email,
                          ],
                          decoration: const InputDecoration(
                            labelText: 'Email',
                          ),
                          onFieldSubmitted: (_) =>
                              _passwordFocus.requestFocus(),
                        ),
                        const SizedBox(height: Space.md),
                        TextFormField(
                          controller: _passwordController,
                          focusNode: _passwordFocus,
                          enabled: !_submitting,
                          obscureText: _obscurePassword,
                          // Autocorrect has no business rewriting a password,
                          // and on-screen suggestions above the keyboard for
                          // one are actively misleading.
                          autocorrect: false,
                          enableSuggestions: false,
                          textInputAction: TextInputAction.done,
                          autofillHints: const [AutofillHints.password],
                          decoration: InputDecoration(
                            labelText: 'Password',
                            suffixIcon: IconButton(
                              onPressed: _submitting
                                  ? null
                                  : () => setState(
                                      () => _obscurePassword =
                                          !_obscurePassword,
                                    ),
                              icon: Icon(
                                _obscurePassword
                                    ? Icons.visibility_outlined
                                    : Icons.visibility_off_outlined,
                              ),
                              tooltip: _obscurePassword
                                  ? 'Show password'
                                  : 'Hide password',
                            ),
                          ),
                          onFieldSubmitted: (_) => _submit(),
                        ),
                        const SizedBox(height: Space.lg),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            onPressed: _submitting ? null : _submit,
                            child: _submitting
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      // Explicit white: the theme's default
                                      // progress indicator colour is amber,
                                      // chosen for pipeline-status tracks and
                                      // barely visible against this button's
                                      // forest fill.
                                      color: C.white,
                                    ),
                                  )
                                : const Text('Sign in'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
