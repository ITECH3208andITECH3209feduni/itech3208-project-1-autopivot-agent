/// The forced password change, shown to any signed-in user whose account
/// still carries a temporary, AutoPivot-generated password.
///
/// Accounts on this platform are never self-registered; every one is
/// provisioned by AutoPivot with a generated password, and `User.
/// mustChangePassword` stays true until that password has been rotated once.
/// The router (built separately) is what actually enforces the redirect and
/// keeps a user with `mustChangePassword == true` here — this screen's job is
/// only to not undermine that: there is deliberately no app bar, no back
/// button, no skip link and no way to pop the route, because a temporary
/// password left in place is exactly the gap this screen exists to close.
///
/// [AuthController.changePassword] does the actual work and, on success,
/// updates the signed-in user in place so `mustChangePassword` becomes false;
/// once that happens the router moves the user on by itself, so this screen
/// does not navigate anywhere and does not need to look at the method's
/// return value.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../widgets/primitives.dart';

/// The server rejects a new password shorter than this (see
/// `AuthController.changePassword`), so the field is validated against the
/// same number before a round trip is ever made.
const _minNewPasswordLength = 12;

class ChangePasswordScreen extends ConsumerStatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  ConsumerState<ChangePasswordScreen> createState() =>
      _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _formKey = GlobalKey<FormState>();

  // Held separately from the controller so the confirm field can be told to
  // re-check itself when the new-password field changes after it, rather than
  // only when the confirm field's own text changes.
  final _confirmFieldKey = GlobalKey<FormFieldState<String>>();

  final _currentController = TextEditingController();
  final _newController = TextEditingController();
  final _confirmController = TextEditingController();

  final _currentFocus = FocusNode();
  final _newFocus = FocusNode();
  final _confirmFocus = FocusNode();

  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  bool _submitting = false;

  /// The server's own sentence for the failed attempt, shown as-is. See
  /// `ApiException.message` — every subtype is written to be safe to display
  /// directly, so there is no client-side copy to write or disagree with.
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    // A confirm value that matched can be made stale by editing the new
    // password afterwards. Re-validate it then, rather than leaving a
    // now-wrong "passwords match" on screen until the confirm field is
    // touched again.
    _newController.addListener(_revalidateConfirmIfTouched);
  }

  @override
  void dispose() {
    _newController.removeListener(_revalidateConfirmIfTouched);
    _currentController.dispose();
    _newController.dispose();
    _confirmController.dispose();
    _currentFocus.dispose();
    _newFocus.dispose();
    _confirmFocus.dispose();
    super.dispose();
  }

  void _revalidateConfirmIfTouched() {
    final confirmState = _confirmFieldKey.currentState;
    if (confirmState != null && (confirmState.value ?? '').isNotEmpty) {
      confirmState.validate();
    }
  }

  String? _validateCurrent(String? value) {
    if (value == null || value.isEmpty) {
      return 'Enter your current password.';
    }
    return null;
  }

  String? _validateNew(String? value) {
    if (value == null || value.isEmpty) {
      return 'Enter a new password.';
    }
    if (value.length < _minNewPasswordLength) {
      return 'Must be at least $_minNewPasswordLength characters.';
    }
    return null;
  }

  String? _validateConfirm(String? value) {
    if (value == null || value.isEmpty) {
      return 'Re-enter your new password.';
    }
    if (value != _newController.text) {
      return 'Passwords do not match.';
    }
    return null;
  }

  Future<void> _submit() async {
    if (_submitting) return;

    // Client-side checks run before the server is ever asked, so a typo in
    // the new password is caught here rather than after a round trip.
    FocusScope.of(context).unfocus();
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _submitting = true;
      _errorMessage = null;
    });

    try {
      await ref
          .read(authProvider.notifier)
          .changePassword(
            currentPassword: _currentController.text,
            newPassword: _newController.text,
          );
      // No navigation here: the auth controller has already updated the
      // signed-in user, and once mustChangePassword reads false the router
      // takes the user on from here by itself.
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // canPop is false and there is no app bar, so there is no gesture, button
    // or route pop that leaves this screen while mustChangePassword is true.
    return PopScope(
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(Space.lg),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: AppCard(
                  child: Form(
                    key: _formKey,
                    autovalidateMode: AutovalidateMode.onUserInteraction,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Set a new password', style: serif(28)),
                        const SizedBox(height: Space.sm),
                        Text(
                          'Your account was created with a temporary '
                          'password. Set your own before you can continue.',
                          style: T.bodySmall,
                        ),
                        const SizedBox(height: Space.lg),
                        if (_errorMessage != null) ...[
                          AppErrorBanner(_errorMessage!),
                          const SizedBox(height: Space.md),
                        ],
                        AutofillGroup(
                          child: Column(
                            children: [
                              _PasswordField(
                                controller: _currentController,
                                focusNode: _currentFocus,
                                label: 'Current password',
                                obscured: _obscureCurrent,
                                onToggleObscured: () => setState(
                                  () => _obscureCurrent = !_obscureCurrent,
                                ),
                                validator: _validateCurrent,
                                textInputAction: TextInputAction.next,
                                autofillHints: const [AutofillHints.password],
                                enabled: !_submitting,
                                onSubmitted: (_) => FocusScope.of(
                                  context,
                                ).requestFocus(_newFocus),
                              ),
                              const SizedBox(height: Space.md),
                              _PasswordField(
                                controller: _newController,
                                focusNode: _newFocus,
                                label: 'New password',
                                obscured: _obscureNew,
                                onToggleObscured: () => setState(
                                  () => _obscureNew = !_obscureNew,
                                ),
                                validator: _validateNew,
                                textInputAction: TextInputAction.next,
                                autofillHints: const [
                                  AutofillHints.newPassword,
                                ],
                                enabled: !_submitting,
                                onSubmitted: (_) => FocusScope.of(
                                  context,
                                ).requestFocus(_confirmFocus),
                              ),
                              const SizedBox(height: Space.md),
                              _PasswordField(
                                formFieldKey: _confirmFieldKey,
                                controller: _confirmController,
                                focusNode: _confirmFocus,
                                label: 'Confirm new password',
                                obscured: _obscureConfirm,
                                onToggleObscured: () => setState(
                                  () => _obscureConfirm = !_obscureConfirm,
                                ),
                                validator: _validateConfirm,
                                textInputAction: TextInputAction.done,
                                autofillHints: const [
                                  AutofillHints.newPassword,
                                ],
                                enabled: !_submitting,
                                onSubmitted: (_) => _submit(),
                              ),
                            ],
                          ),
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
                                      color: C.white,
                                    ),
                                  )
                                : const Text('Change password'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// One obscured field with a reveal toggle.
///
/// Pulled out of `build` because the three fields differ only in their label,
/// controller, focus handling and autofill hint — repeating the rest three
/// times is exactly the kind of drift the design system guidelines warn
/// about.
class _PasswordField extends StatelessWidget {
  const _PasswordField({
    required this.controller,
    required this.focusNode,
    required this.label,
    required this.obscured,
    required this.onToggleObscured,
    required this.validator,
    required this.textInputAction,
    required this.autofillHints,
    required this.enabled,
    required this.onSubmitted,
    this.formFieldKey,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final String label;
  final bool obscured;
  final VoidCallback onToggleObscured;
  final FormFieldValidator<String> validator;
  final TextInputAction textInputAction;
  final List<String> autofillHints;
  final bool enabled;
  final ValueChanged<String> onSubmitted;
  final GlobalKey<FormFieldState<String>>? formFieldKey;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      key: formFieldKey,
      controller: controller,
      focusNode: focusNode,
      enabled: enabled,
      obscureText: obscured,
      keyboardType: TextInputType.visiblePassword,
      autofillHints: autofillHints,
      textInputAction: textInputAction,
      onFieldSubmitted: onSubmitted,
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        suffixIcon: IconButton(
          onPressed: enabled ? onToggleObscured : null,
          tooltip: obscured ? 'Show password' : 'Hide password',
          icon: Icon(
            obscured ? Icons.visibility_outlined : Icons.visibility_off_outlined,
            color: C.inkSoft,
          ),
        ),
      ),
    );
  }
}
