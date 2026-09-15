/// Mirrors `DealershipUserOut` in `api/schemas.py` — one row of a
/// dealership's own team, as returned by `GET /api/dealership/users` and
/// embedded in the create/reset responses below.
library;

class DealershipUser {
  const DealershipUser({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.role,
    required this.isActive,
    required this.mustChangePassword,
  });

  final int id;
  final String email;
  final String firstName;
  final String lastName;

  /// `dealership_admin` or `dealership_staff` — the same two values the
  /// server's `role_allowed` check constraint permits at this scope; see
  /// `database/models.py`. A platform administrator is never returned here
  /// at all, since this endpoint is itself scoped to one dealership.
  final String role;

  final bool isActive;
  final bool mustChangePassword;

  String get displayName => '$firstName $lastName'.trim();

  bool get isAdmin => role == 'dealership_admin';

  factory DealershipUser.fromJson(Map<String, dynamic> json) =>
      DealershipUser(
        id: json['id'] as int,
        email: json['email'] as String,
        firstName: json['first_name'] as String,
        lastName: json['last_name'] as String,
        role: json['role'] as String,
        isActive: json['is_active'] as bool,
        mustChangePassword: json['must_change_password'] as bool,
      );
}

/// A freshly created account — mirrors `DealershipUserProvisionedOut`.
/// [initialPassword] is server-generated and shown to the caller exactly
/// once; the server itself never returns it again after this response, so
/// there is nothing to re-fetch if it is lost.
class DealershipUserProvisioned {
  const DealershipUserProvisioned({
    required this.user,
    required this.initialPassword,
  });

  final DealershipUser user;
  final String initialPassword;

  factory DealershipUserProvisioned.fromJson(Map<String, dynamic> json) =>
      DealershipUserProvisioned(
        user: DealershipUser.fromJson(json['user'] as Map<String, dynamic>),
        initialPassword: json['initial_password'] as String,
      );
}
