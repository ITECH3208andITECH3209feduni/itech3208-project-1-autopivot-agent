/// Mirrors `UserOut` in `api/schemas.py`.
library;

import 'dealership.dart';

class User {
  const User({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.role,
    required this.isActive,
    required this.mustChangePassword,
    required this.dealership,
  });

  final int id;
  final String email;
  final String firstName;
  final String lastName;
  final String role;
  final bool isActive;

  /// Accounts are provisioned by AutoPivot with a generated password, so this
  /// is true on a first sign-in and the user cannot go anywhere else until it
  /// is false. There is no registration on any platform — a client decision,
  /// not an omission.
  final bool mustChangePassword;

  /// Null for a platform administrator, who belongs to no single dealership.
  final Dealership? dealership;

  String get displayName => '$firstName $lastName'.trim();

  factory User.fromJson(Map<String, dynamic> json) => User(
    id: json['id'] as int,
    email: json['email'] as String,
    firstName: json['first_name'] as String? ?? '',
    lastName: json['last_name'] as String? ?? '',
    role: json['role'] as String,
    isActive: json['is_active'] as bool? ?? true,
    mustChangePassword: json['must_change_password'] as bool? ?? false,
    dealership: json['dealership'] == null
        ? null
        : Dealership.fromJson(json['dealership'] as Map<String, dynamic>),
  );
}
