/// A dealership's team roster: add a member, reset a password, deactivate an
/// account.
///
/// Serves two different callers, distinguished only by whether
/// [TeamScreen.dealershipId] is set:
///
///  * Null — a `dealership_admin` managing their own team, reached from the
///    account sheet's Settings row. Calls the unscoped
///    `/api/dealership/users` endpoints, which take the caller's own
///    dealership from their token.
///  * Set — a `platform_admin` managing one specific dealership's team,
///    reached by tapping a row on `dealerships_screen.dart`. Calls the
///    `/api/platform/dealerships/{id}/users` endpoints instead, which take
///    the dealership explicitly since a platform administrator belongs to
///    none of their own.
///
/// One screen rather than two near-identical copies: the interaction is
/// genuinely identical either way (list, add, reset, deactivate), and the
/// only thing that differs is which four endpoints back it — see
/// [_TeamScreenState._forPlatform] for where that split actually happens.
/// The role checks that gate reaching this screen at all (Settings row,
/// dealership row) are a UX convenience, not the real security boundary:
/// every endpoint here is independently gated server-side
/// (`require_roles("dealership_admin")` / `require_roles("platform_admin")`
/// in `api/routes_dealership_users.py` / `api/routes_platform_dealership_users.py`),
/// so a stale or tampered client state still can't reach another
/// dealership's accounts, only get a 403 shown as an ordinary
/// [ApiException].
///
/// Ported from the web platform's `DealershipUsersPage.tsx` rather than
/// designed from scratch — same fields, same one-time password reveal, same
/// "no reactivate" limitation (the server has no such endpoint, so neither
/// does this) — so a dealer who has used the platform finds the same thing
/// here, and "on the go" genuinely means the same capability, not a
/// smaller lookalike of it.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models/dealership_user.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../settings/app_preferences.dart';
import '../../widgets/primitives.dart';
import '../../widgets/skeleton.dart';

// ── Load state ──────────────────────────────────────────────────────────────

/// What the screen currently has to show — the same three-state shape as
/// `listing_detail_screen.dart`'s `_Load`, for the same reason: the states
/// are mutually exclusive, and the compiler should enforce that rather than
/// a loading flag plus a nullable list plus a nullable error message.
sealed class _Load {
  const _Load();
}

final class _Loading extends _Load {
  const _Loading();
}

final class _Loaded extends _Load {
  const _Loaded(this.users);
  final List<DealershipUser> users;
}

final class _LoadFailed extends _Load {
  const _LoadFailed(this.message);

  /// Already safe to show as-is — see [ApiException.message].
  final String message;
}

// ── Screen ───────────────────────────────────────────────────────────────────

class TeamScreen extends ConsumerStatefulWidget {
  const TeamScreen({super.key, this.dealershipId, this.dealershipName});

  /// Set only when a platform administrator is viewing a dealership other
  /// than their own (they have none) — see this file's own top doc comment.
  final int? dealershipId;

  /// Only meaningful alongside [dealershipId] — shown in the header in place
  /// of "your dealership".
  final String? dealershipName;

  @override
  ConsumerState<TeamScreen> createState() => _TeamScreenState();
}

class _TeamScreenState extends ConsumerState<TeamScreen> {
  _Load _state = const _Loading();

  bool get _forPlatform => widget.dealershipId != null;

  /// Ids currently mid-action (reset or deactivate) — keyed per user, the
  /// same reason `listing_detail_screen.dart` keys its own busy set by image
  /// id: acting on one row should not freeze every other row in the list.
  Set<int> _busyIds = const {};

  /// The most recent add/reset/deactivate failure. Cleared at the start of
  /// the next attempt rather than on a timer — the initial list load has its
  /// own separate failure state, [_LoadFailed], since a load failure means
  /// there is nothing to show at all and an action failure means the list
  /// on screen is still good.
  String? _errorMessage;

  final _searchController = TextEditingController();
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
    _searchController.addListener(() {
      setState(() => _query = _searchController.text.trim().toLowerCase());
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// Matching users first, most-recently-relevant order — active before
  /// deactivated, so a roster you actually manage day to day is not
  /// interleaved with accounts that no longer sign in. Client-side, not a
  /// server query: this screen already holds the whole team in memory, and
  /// a dealership's roster is small enough that filtering it here costs
  /// nothing worth a round trip to avoid.
  List<DealershipUser> _visibleUsers(List<DealershipUser> users) {
    final matching = _query.isEmpty
        ? users
        : users.where((u) {
            final haystack = '${u.displayName} ${u.email}'.toLowerCase();
            return haystack.contains(_query);
          }).toList();

    return [...matching]..sort((a, b) {
      if (a.isActive != b.isActive) return a.isActive ? -1 : 1;
      return a.displayName.toLowerCase().compareTo(b.displayName.toLowerCase());
    });
  }

  Future<void> _load() async {
    setState(() => _state = const _Loading());
    final api = ref.read(apiClientProvider);
    try {
      final users = _forPlatform
          ? await api.platformDealershipUsers(widget.dealershipId!)
          : await api.dealershipUsers();
      if (!mounted) return;
      setState(() => _state = _Loaded(users));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  Future<void> _openAddSheet() async {
    final form = await showModalBottomSheet<_NewTeamMemberForm>(
      context: context,
      isScrollControlled: true,
      backgroundColor: C.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => const _AddTeamMemberSheet(),
    );
    if (form == null || !mounted) return;

    setState(() => _errorMessage = null);
    try {
      final api = ref.read(apiClientProvider);
      final created = _forPlatform
          ? await api.addPlatformDealershipUser(
              widget.dealershipId!,
              email: form.email,
              firstName: form.firstName,
              lastName: form.lastName,
              role: form.role,
            )
          : await api.addDealershipUser(
              email: form.email,
              firstName: form.firstName,
              lastName: form.lastName,
              role: form.role,
            );
      if (!mounted) return;
      await _load();
      if (!mounted) return;
      await _showInitialPassword(
        email: created.user.email,
        password: created.initialPassword,
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _errorMessage = e.message);
    }
  }

  Future<void> _resetPassword(DealershipUser target) async {
    if (_busyIds.contains(target.id)) return;
    setState(() {
      _busyIds = {..._busyIds, target.id};
      _errorMessage = null;
    });

    try {
      final api = ref.read(apiClientProvider);
      final password = _forPlatform
          ? await api.resetPlatformDealershipUserPassword(
              widget.dealershipId!,
              target.id,
            )
          : await api.resetDealershipUserPassword(target.id);
      if (!mounted) return;
      setState(() => _busyIds = {..._busyIds}..remove(target.id));
      await _showInitialPassword(email: target.email, password: password);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busyIds = {..._busyIds}..remove(target.id);
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _deactivate(DealershipUser target) async {
    if (_busyIds.contains(target.id)) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => _DeactivateConfirmDialog(user: target),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _busyIds = {..._busyIds, target.id};
      _errorMessage = null;
    });

    try {
      final api = ref.read(apiClientProvider);
      final updated = _forPlatform
          ? await api.deactivatePlatformDealershipUser(
              widget.dealershipId!,
              target.id,
            )
          : await api.deactivateDealershipUser(target.id);
      if (!mounted) return;

      // Re-read the current state rather than closing over the list this
      // method started with, the same reasoning listing_detail_screen.dart
      // uses for its own delete: nothing else can mutate it between the
      // await above and here, but reading it fresh is what actually
      // justifies that rather than just assuming it.
      final current = _state;
      if (current is _Loaded) {
        final users = [
          for (final u in current.users) u.id == updated.id ? updated : u,
        ];
        setState(() {
          _state = _Loaded(users);
          _busyIds = {..._busyIds}..remove(target.id);
        });
      }
      if (!mounted) return;
      haptic(ref, HapticFeedbackType.medium);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${target.displayName} deactivated')),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busyIds = {..._busyIds}..remove(target.id);
        _errorMessage = e.message;
      });
    }
  }

  Future<void> _showInitialPassword({
    required String email,
    required String password,
  }) {
    return showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) =>
          _InitialPasswordDialog(email: email, password: password),
    );
  }

  IconButton _backButton() => IconButton(
    onPressed: () => Navigator.of(context).pop(),
    icon: const Icon(Icons.arrow_back, color: C.inkSoft),
    tooltip: 'Back',
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(body: SafeArea(child: _content(_state)));
  }

  Widget _content(_Load state) => switch (state) {
    _Loading() => _loadingBody(),
    _LoadFailed(:final message) => _failedBody(message),
    _Loaded(:final users) => _loadedBody(users),
  };

  Widget _loadingBody() => Column(
    children: [
      Align(alignment: Alignment.centerLeft, child: _backButton()),
      Expanded(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            Space.lg,
            Space.sm,
            Space.lg,
            Space.lg,
          ),
          child: ShimmerGroup(
            child: Column(
              children: [
                for (var i = 0; i < 4; i++) ...[
                  const SkeletonCard(lines: [0.45]),
                  if (i < 3) const SizedBox(height: Space.sm),
                ],
              ],
            ),
          ),
        ),
      ),
    ],
  );

  Widget _failedBody(String message) => Column(
    children: [
      Align(alignment: Alignment.centerLeft, child: _backButton()),
      Expanded(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Space.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AppErrorBanner(message),
                const SizedBox(height: Space.lg),
                FilledButton(onPressed: _load, child: const Text('Try again')),
              ],
            ),
          ),
        ),
      ),
    ],
  );

  Widget _loadedBody(List<DealershipUser> users) {
    final currentUser = ref.watch(currentUserProvider);
    final visible = _visibleUsers(users);

    return CustomScrollView(
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
        if (users.length > 1)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.md),
            sliver: SliverToBoxAdapter(
              child: SearchField(
                controller: _searchController,
                hintText: 'Search by name or email',
              ),
            ),
          ),
        if (_errorMessage != null)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.md),
            sliver: SliverToBoxAdapter(child: AppErrorBanner(_errorMessage!)),
          ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.xl),
          sliver: users.isEmpty
              ? const SliverToBoxAdapter(
                  child: EmptyState(
                    title: 'No team accounts yet',
                    body: 'Add the first person on your team below.',
                  ),
                )
              : visible.isEmpty
              ? const SliverToBoxAdapter(
                  child: EmptyState(
                    title: 'No one matches',
                    body: 'Try a different name or email.',
                  ),
                )
              : SliverList.separated(
                  itemCount: visible.length,
                  separatorBuilder: (context, index) =>
                      const SizedBox(height: Space.sm),
                  itemBuilder: (context, index) {
                    final target = visible[index];
                    return _TeamMemberRow(
                      user: target,
                      isSelf: target.id == currentUser?.id,
                      busy: _busyIds.contains(target.id),
                      onResetPassword: () => _resetPassword(target),
                      onDeactivate: () => _deactivate(target),
                    );
                  },
                ),
        ),
      ],
    );
  }

  /// Back button, title, and the add-member action — the same row shape as
  /// `listing_detail_screen.dart`'s own header, with one more thing in it.
  Widget _header() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _backButton(),
        const SizedBox(width: Space.xs),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(top: Space.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _forPlatform ? widget.dealershipName ?? 'Team' : 'Team',
                  style: serif(28),
                ),
                const SizedBox(height: Space.xs),
                Text(
                  _forPlatform
                      ? 'Add, reset or deactivate accounts for this dealership.'
                      : 'Add, reset or deactivate accounts for your dealership.',
                  style: T.bodySmall,
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: Space.xs),
          child: Semantics(
            button: true,
            label: 'Add team member',
            excludeSemantics: true,
            child: IconButton(
              onPressed: _openAddSheet,
              icon: const Icon(
                Icons.person_add_alt_1_outlined,
                color: C.forest,
              ),
              tooltip: 'Add team member',
            ),
          ),
        ),
      ],
    );
  }
}

// ── Team member row ──────────────────────────────────────────────────────────

enum _TeamAction { reset, deactivate }

class _TeamMemberRow extends StatelessWidget {
  const _TeamMemberRow({
    required this.user,
    required this.isSelf,
    required this.busy,
    required this.onResetPassword,
    required this.onDeactivate,
  });

  final DealershipUser user;
  final bool isSelf;
  final bool busy;
  final VoidCallback onResetPassword;
  final VoidCallback onDeactivate;

  @override
  Widget build(BuildContext context) {
    final roleLabel = user.isAdmin ? 'Administrator' : 'Staff';
    final subtitle = [
      user.email,
      roleLabel,
      if (!user.isActive) 'Deactivated',
    ].join(' · ');

    return AppCard(
      padding: const EdgeInsets.symmetric(
        horizontal: Space.md,
        vertical: Space.sm,
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  user.displayName,
                  style: T.label.copyWith(
                    color: user.isActive ? C.ink : C.inkSoft,
                  ),
                ),
                const SizedBox(height: 2),
                Text(subtitle, style: T.bodySmall),
              ],
            ),
          ),
          if (busy)
            const Padding(
              padding: EdgeInsets.all(Space.sm),
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          // Matches the platform exactly: there is no way back from
          // deactivated short of a new account, so a deactivated row offers
          // neither action rather than one that would 404.
          else if (user.isActive)
            PopupMenuButton<_TeamAction>(
              icon: const Icon(Icons.more_vert, color: C.inkSoft),
              tooltip: 'Actions',
              onSelected: (action) => switch (action) {
                _TeamAction.reset => onResetPassword(),
                _TeamAction.deactivate => onDeactivate(),
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: _TeamAction.reset,
                  child: Text('Reset password'),
                ),
                // A person cannot deactivate their own account — the server
                // enforces this too (see routes_dealership_users.py), but
                // offering the action here just to have it refused is worse
                // than not offering it.
                if (!isSelf)
                  const PopupMenuItem(
                    value: _TeamAction.deactivate,
                    child: Text('Deactivate', style: TextStyle(color: C.rust)),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

// ── Add team member ──────────────────────────────────────────────────────────

/// What the add sheet hands back — plain data, not a network call. The
/// sheet's only job is collecting and validating; `_TeamScreenState`
/// performs the actual request afterward and owns whatever it does with the
/// result, the same split `review_screen.dart`'s overview step uses for the
/// same reason: a sheet or screen mid-close is not somewhere to be juggling
/// a request's error state.
class _NewTeamMemberForm {
  const _NewTeamMemberForm({
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.role,
  });

  final String email;
  final String firstName;
  final String lastName;
  final String role;
}

class _AddTeamMemberSheet extends StatefulWidget {
  const _AddTeamMemberSheet();

  @override
  State<_AddTeamMemberSheet> createState() => _AddTeamMemberSheetState();
}

class _AddTeamMemberSheetState extends State<_AddTeamMemberSheet> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  String _role = 'dealership_staff';

  @override
  void dispose() {
    _emailController.dispose();
    _firstNameController.dispose();
    _lastNameController.dispose();
    super.dispose();
  }

  void _confirm() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.of(context).pop(
      _NewTeamMemberForm(
        email: _emailController.text.trim(),
        firstName: _firstNameController.text.trim(),
        lastName: _lastNameController.text.trim(),
        role: _role,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        Space.lg,
        Space.lg,
        Space.lg,
        Space.lg + MediaQuery.of(context).viewInsets.bottom,
      ),
      child: Form(
        key: _formKey,
        autovalidateMode: AutovalidateMode.onUserInteraction,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Add team member', style: serif(24)),
            const SizedBox(height: Space.xs),
            Text(
              'A temporary password is generated automatically — you\'ll '
              'see it once, right after this.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            TextFormField(
              controller: _emailController,
              keyboardType: TextInputType.emailAddress,
              textCapitalization: TextCapitalization.none,
              decoration: const InputDecoration(labelText: 'Email'),
              validator: (value) {
                final trimmed = value?.trim() ?? '';
                if (trimmed.isEmpty) return 'Required';
                if (!trimmed.contains('@')) return 'Enter a valid email';
                return null;
              },
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _firstNameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'First name'),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? 'Required' : null,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _lastNameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Last name'),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? 'Required' : null,
            ),
            const SizedBox(height: Space.md),
            DropdownButtonFormField<String>(
              initialValue: _role,
              decoration: const InputDecoration(labelText: 'Role'),
              items: const [
                DropdownMenuItem(
                  value: 'dealership_staff',
                  child: Text('Staff'),
                ),
                DropdownMenuItem(
                  value: 'dealership_admin',
                  child: Text('Administrator'),
                ),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _role = value);
              },
            ),
            const SizedBox(height: Space.lg),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _confirm,
                child: const Text('Add'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Dialogs ──────────────────────────────────────────────────────────────────

/// The one-time password reveal — shown after adding a user or resetting
/// one's password, and never retrievable again after this, since the server
/// itself never returns it a second time. `barrierDismissible: false` on
/// the caller's `showDialog` is deliberate for the same reason: an accidental
/// tap outside the dialog must not lose it before it has been read or
/// copied.
class _InitialPasswordDialog extends StatelessWidget {
  const _InitialPasswordDialog({required this.email, required this.password});

  final String email;
  final String password;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: C.white,
      shape: const RoundedRectangleBorder(borderRadius: Radii.cardAll),
      child: Padding(
        padding: const EdgeInsets.all(Space.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Initial password', style: serif(24)),
            const SizedBox(height: Space.sm),
            Text(
              'For $email. Shown only now — share it securely. They must '
              'change it at sign-in.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(Space.md),
              decoration: BoxDecoration(
                color: C.bone,
                borderRadius: Radii.controlAll,
              ),
              child: SelectableText(
                password,
                style: T.figure.copyWith(fontSize: 15),
              ),
            ),
            const SizedBox(height: Space.lg),
            Row(
              children: [
                // Expanded on both, matching capture_screen.dart's own note
                // on its equivalent pair: FilledButtonThemeData's house-wide
                // minimumSize is full-width, which needs a finite width to
                // size against inside a bare Row.
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () async {
                      await Clipboard.setData(ClipboardData(text: password));
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Password copied')),
                        );
                      }
                    },
                    icon: const Icon(Icons.copy_outlined, size: 18),
                    label: const Text('Copy'),
                  ),
                ),
                const SizedBox(width: Space.sm),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Done'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Confirms before deactivating — the same shape as
/// `listing_detail_screen.dart`'s own delete confirmation, since this
/// codebase has no shared confirm-dialog primitive yet (per that file's own
/// note, that exists on the web client, not here).
class _DeactivateConfirmDialog extends StatelessWidget {
  const _DeactivateConfirmDialog({required this.user});

  final DealershipUser user;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: C.white,
      shape: const RoundedRectangleBorder(borderRadius: Radii.cardAll),
      child: Padding(
        padding: const EdgeInsets.all(Space.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Deactivate this account?', style: serif(24)),
            const SizedBox(height: Space.sm),
            Text(
              '${user.displayName} will lose access to AutoPivot '
              'immediately. This cannot be undone from here.',
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    child: const Text('Cancel'),
                  ),
                ),
                const SizedBox(width: Space.sm),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: C.rust,
                      minimumSize: const Size(0, 48),
                    ),
                    onPressed: () => Navigator.of(context).pop(true),
                    child: const Text('Deactivate'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
