/// Mirrors `DealershipProvisionedOut` in `api/schemas.py` — the response to
/// `POST /api/platform/dealerships`.
///
/// A standalone file rather than living in `dealership.dart` or `user.dart`:
/// it needs both of those models, and `user.dart` already imports
/// `dealership.dart` for `User.dealership`, so putting this here is what
/// keeps that pair from needing to import each other.
library;

import 'dealership.dart';
import 'user.dart';

class DealershipProvisioned {
  const DealershipProvisioned({
    required this.dealership,
    required this.administrator,
    required this.initialPassword,
  });

  final Dealership dealership;
  final User administrator;

  /// Server-generated, shown to the caller exactly once — see
  /// `DealershipUserProvisioned.initialPassword`'s doc comment in
  /// `dealership_user.dart` for the same rule applied to a dealership's own
  /// team; this is the identical shape one level up, for a dealership's
  /// first account instead of one added to an existing dealership.
  final String initialPassword;

  factory DealershipProvisioned.fromJson(Map<String, dynamic> json) =>
      DealershipProvisioned(
        dealership: Dealership.fromJson(
          json['dealership'] as Map<String, dynamic>,
        ),
        administrator: User.fromJson(
          json['administrator'] as Map<String, dynamic>,
        ),
        initialPassword: json['initial_password'] as String,
      );
}
