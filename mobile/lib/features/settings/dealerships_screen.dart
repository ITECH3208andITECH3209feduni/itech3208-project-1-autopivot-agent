/// Platform administration: every dealership on AutoPivot, and onboarding a
/// new one.
///
/// A `platform_admin`'s home screen (`app.dart`'s redirect sends them here
/// instead of the vehicles list, which has nothing for a role attached to no
/// dealership) — reached both as that home and, same as `team_screen.dart`,
/// as a drill-down from the account sheet's Settings row; either way it is
/// only ever offered to a `platform_admin` — see `widgets/app_shell.dart`.
/// That role check is a UX convenience, not the real security boundary: both
/// endpoints this screen calls are independently gated the same way
/// server-side (`require_roles("platform_admin")` in
/// `api/routes_platform_admin.py`).
///
/// Ported from the web platform's `PlatformAdminPage.tsx` — same fields,
/// same one-time password reveal for the dealership's first account, and
/// the same thing a row's name now does: tapping it opens that dealership's
/// team (`team_screen.dart`, reached via `AppRoutes.dealershipTeam`), the
/// mobile equivalent of the platform's expandable panel under each row.
/// There is nothing else to do to a dealership itself once created — no
/// reset, no deactivate, no edit — because the platform page offers none of
/// those either; onboarding and team management are the whole feature today.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/api_exception.dart';
import '../../api/models/dealership.dart';
import '../../auth/auth_controller.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../routes.dart';
import '../../widgets/primitives.dart';

// ── Load state ──────────────────────────────────────────────────────────────

/// Same three-state shape as `team_screen.dart`'s own `_Load`, for the same
/// reason: loading, loaded and failed are mutually exclusive, and the
/// compiler should enforce that rather than a flag plus two nullables.
sealed class _Load {
  const _Load();
}

final class _Loading extends _Load {
  const _Loading();
}

final class _Loaded extends _Load {
  const _Loaded(this.dealerships);
  final List<Dealership> dealerships;
}

final class _LoadFailed extends _Load {
  const _LoadFailed(this.message);

  /// Already safe to show as-is — see [ApiException.message].
  final String message;
}

// ── Screen ───────────────────────────────────────────────────────────────────

class DealershipsScreen extends ConsumerStatefulWidget {
  const DealershipsScreen({super.key});

  @override
  ConsumerState<DealershipsScreen> createState() => _DealershipsScreenState();
}

class _DealershipsScreenState extends ConsumerState<DealershipsScreen> {
  _Load _state = const _Loading();

  /// The most recent onboarding failure — a separate state from
  /// [_LoadFailed] for the same reason `team_screen.dart` keeps its own
  /// action errors apart from its load error: a failed creation leaves the
  /// list on screen still good, so there is no reason to replace it with an
  /// error body.
  String? _errorMessage;

  bool _creating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _state = const _Loading());
    final api = ref.read(apiClientProvider);
    try {
      final dealerships = await api.platformDealerships();
      if (!mounted) return;
      setState(() => _state = _Loaded(dealerships));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _state = _LoadFailed(e.message));
    }
  }

  Future<void> _openCreateSheet() async {
    final form = await showModalBottomSheet<_NewDealershipForm>(
      context: context,
      isScrollControlled: true,
      backgroundColor: C.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => const _CreateDealershipSheet(),
    );
    if (form == null || !mounted) return;

    setState(() {
      _creating = true;
      _errorMessage = null;
    });
    try {
      final created = await ref
          .read(apiClientProvider)
          .onboardDealership(
            name: form.name,
            location: form.location,
            contactName: form.contactName,
            contactEmail: form.contactEmail,
            contactPhone: form.contactPhone,
            adminEmail: form.adminEmail,
            adminFirstName: form.adminFirstName,
            adminLastName: form.adminLastName,
          );
      if (!mounted) return;
      setState(() => _creating = false);
      await _load();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => _DealershipCreatedDialog(
          dealershipName: created.dealership.name,
          adminEmail: created.administrator.email,
          password: created.initialPassword,
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _errorMessage = e.message;
      });
    }
  }

  /// Empty when there is nothing to pop to — true when this screen is
  /// platform_admin's home rather than a Settings drill-down (see
  /// `app.dart`'s route registration for [AppRoutes.dealerships]), the same
  /// way `listings_screen.dart` has never needed a back button for the same
  /// reason.
  Widget _backButton() {
    if (!Navigator.of(context).canPop()) return const SizedBox.shrink();
    return IconButton(
      onPressed: () => Navigator.of(context).pop(),
      icon: const Icon(Icons.arrow_back, color: C.inkSoft),
      tooltip: 'Back',
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(body: SafeArea(child: _content(_state)));
  }

  Widget _content(_Load state) => switch (state) {
    _Loading() => _loadingBody(),
    _LoadFailed(:final message) => _failedBody(message),
    _Loaded(:final dealerships) => _loadedBody(dealerships),
  };

  Widget _loadingBody() => Column(
    children: [
      Align(alignment: Alignment.centerLeft, child: _backButton()),
      const Expanded(child: Center(child: CircularProgressIndicator())),
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

  Widget _loadedBody(List<Dealership> dealerships) {
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
        if (_errorMessage != null)
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(
              Space.lg,
              0,
              Space.lg,
              Space.md,
            ),
            sliver: SliverToBoxAdapter(child: AppErrorBanner(_errorMessage!)),
          ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(Space.lg, 0, Space.lg, Space.xl),
          sliver: dealerships.isEmpty
              ? const SliverToBoxAdapter(
                  child: EmptyState(
                    title: 'No dealerships yet',
                    body: 'Create the first one below.',
                  ),
                )
              : SliverList.separated(
                  itemCount: dealerships.length,
                  separatorBuilder: (context, index) =>
                      const SizedBox(height: Space.sm),
                  itemBuilder: (context, index) =>
                      _DealershipRow(dealership: dealerships[index]),
                ),
        ),
      ],
    );
  }

  /// Back button, title, and the create action — the same row shape as
  /// `team_screen.dart`'s own header, disabled while a creation is already
  /// in flight rather than allowing a second tap to start another.
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
                Text('Dealerships', style: serif(28)),
                const SizedBox(height: Space.xs),
                Text(
                  'Create a dealership and its first administrator account.',
                  style: T.bodySmall,
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: Space.xs),
          child: _creating
              ? const Padding(
                  padding: EdgeInsets.all(Space.sm),
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                )
              : Semantics(
                  button: true,
                  label: 'Create dealership',
                  excludeSemantics: true,
                  child: IconButton(
                    onPressed: _openCreateSheet,
                    icon: const Icon(Icons.add_business_outlined, color: C.forest),
                    tooltip: 'Create dealership',
                  ),
                ),
        ),
      ],
    );
  }
}

// ── Dealership row ───────────────────────────────────────────────────────────

class _DealershipRow extends StatelessWidget {
  const _DealershipRow({required this.dealership});

  final Dealership dealership;

  @override
  Widget build(BuildContext context) {
    final subtitle = [
      dealership.location,
      dealership.contactName,
      dealership.contactEmail,
      dealership.contactPhone,
    ].whereType<String>().where((s) => s.isNotEmpty).join(' · ');

    return InkWell(
      borderRadius: Radii.cardAll,
      onTap: () => context.push(
        AppRoutes.dealershipTeamPath(dealership.id),
        extra: dealership.name,
      ),
      child: AppCard(
        padding: const EdgeInsets.symmetric(
          horizontal: Space.md,
          vertical: Space.sm,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(dealership.name, style: T.label),
                  if (subtitle.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(subtitle, style: T.bodySmall),
                  ],
                ],
              ),
            ),
            const SizedBox(width: Space.sm),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(dealership.status, style: T.caption),
                const SizedBox(height: 2),
                Text(
                  '${dealership.userCount} user'
                  '${dealership.userCount == 1 ? '' : 's'}',
                  style: T.caption,
                ),
              ],
            ),
            const SizedBox(width: Space.xs),
            const Icon(Icons.chevron_right, size: 18, color: C.lineStrong),
          ],
        ),
      ),
    );
  }
}

// ── Create dealership ────────────────────────────────────────────────────────

/// What the create sheet hands back — plain data, not a network call. Same
/// split as `team_screen.dart`'s `_NewTeamMemberForm`: the sheet only
/// collects and validates, `_DealershipsScreenState` performs the request
/// and owns whatever it does with the result.
class _NewDealershipForm {
  const _NewDealershipForm({
    required this.name,
    required this.location,
    required this.contactName,
    required this.contactEmail,
    required this.contactPhone,
    required this.adminEmail,
    required this.adminFirstName,
    required this.adminLastName,
  });

  final String name;
  final String location;
  final String contactName;
  final String contactEmail;
  final String contactPhone;
  final String adminEmail;
  final String adminFirstName;
  final String adminLastName;
}

class _CreateDealershipSheet extends StatefulWidget {
  const _CreateDealershipSheet();

  @override
  State<_CreateDealershipSheet> createState() =>
      _CreateDealershipSheetState();
}

class _CreateDealershipSheetState extends State<_CreateDealershipSheet> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _locationController = TextEditingController();
  final _contactNameController = TextEditingController();
  final _contactEmailController = TextEditingController();
  final _contactPhoneController = TextEditingController();
  final _adminEmailController = TextEditingController();
  final _adminFirstNameController = TextEditingController();
  final _adminLastNameController = TextEditingController();

  @override
  void dispose() {
    _nameController.dispose();
    _locationController.dispose();
    _contactNameController.dispose();
    _contactEmailController.dispose();
    _contactPhoneController.dispose();
    _adminEmailController.dispose();
    _adminFirstNameController.dispose();
    _adminLastNameController.dispose();
    super.dispose();
  }

  String? _required(String? value) =>
      (value == null || value.trim().isEmpty) ? 'Required' : null;

  String? _requiredEmail(String? value) {
    final trimmed = value?.trim() ?? '';
    if (trimmed.isEmpty) return 'Required';
    if (!trimmed.contains('@')) return 'Enter a valid email';
    return null;
  }

  void _confirm() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.of(context).pop(
      _NewDealershipForm(
        name: _nameController.text.trim(),
        location: _locationController.text.trim(),
        contactName: _contactNameController.text.trim(),
        contactEmail: _contactEmailController.text.trim(),
        contactPhone: _contactPhoneController.text.trim(),
        adminEmail: _adminEmailController.text.trim(),
        adminFirstName: _adminFirstNameController.text.trim(),
        adminLastName: _adminLastNameController.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Eight fields is more than any other sheet in this app shows at once
    // (team_screen.dart's add sheet has four) — SingleChildScrollView is
    // what keeps this usable with the keyboard open on a phone, where the
    // sheet's own height is a fraction of the screen rather than all of it.
    return SingleChildScrollView(
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
            Text('New dealership', style: serif(24)),
            const SizedBox(height: Space.xs),
            Text(
              'Creates the dealership and its first administrator account '
              'together. A temporary password is generated automatically — '
              "you'll see it once, right after this.",
              style: T.bodySmall,
            ),
            const SizedBox(height: Space.lg),
            Text('DEALERSHIP', style: T.caption),
            const SizedBox(height: Space.sm),
            TextFormField(
              controller: _nameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Dealership name'),
              validator: _required,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _locationController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Location'),
              validator: _required,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _contactNameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Contact name'),
              validator: _required,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _contactEmailController,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Contact email'),
              validator: _requiredEmail,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _contactPhoneController,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'Contact phone'),
              validator: _required,
            ),
            const SizedBox(height: Space.lg),
            Text('FIRST ADMINISTRATOR', style: T.caption),
            const SizedBox(height: Space.sm),
            TextFormField(
              controller: _adminEmailController,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                labelText: 'Administrator email',
              ),
              validator: _requiredEmail,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _adminFirstNameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'First name'),
              validator: _required,
            ),
            const SizedBox(height: Space.md),
            TextFormField(
              controller: _adminLastNameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Last name'),
              validator: _required,
            ),
            const SizedBox(height: Space.lg),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _confirm,
                child: const Text('Create dealership'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Dialogs ──────────────────────────────────────────────────────────────────

/// The one-time password reveal for a dealership's first account — the same
/// shape and the same reasoning as `team_screen.dart`'s
/// `_InitialPasswordDialog` (`barrierDismissible: false` for the same
/// reason: an accidental tap outside it must not lose a password that
/// cannot be fetched again), with a dealership name alongside the admin's
/// email since this one is confirming two things were just created, not
/// one.
class _DealershipCreatedDialog extends StatelessWidget {
  const _DealershipCreatedDialog({
    required this.dealershipName,
    required this.adminEmail,
    required this.password,
  });

  final String dealershipName;
  final String adminEmail;
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
            Text('$dealershipName was created', style: serif(24)),
            const SizedBox(height: Space.sm),
            Text(
              'Initial password for $adminEmail. Shown only now — share it '
              'securely. They must change it at sign-in.',
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
