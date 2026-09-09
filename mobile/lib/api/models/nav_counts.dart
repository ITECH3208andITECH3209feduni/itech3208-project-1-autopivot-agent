/// Mirrors `NavCounts` in `api/schemas.py`, served by `/api/dashboard/counts`.
///
/// Deliberately not `DashboardStats`, which is scoped to the current month and
/// would be the wrong number to show beside a total.
library;

class NavCounts {
  const NavCounts({
    required this.vehicles,
    required this.backdrops,
    required this.needsReview,
  });

  final int vehicles;
  final int backdrops;
  final int needsReview;

  factory NavCounts.fromJson(Map<String, dynamic> json) => NavCounts(
    vehicles: json['vehicles'] as int? ?? 0,
    backdrops: json['backdrops'] as int? ?? 0,
    needsReview: json['needs_review'] as int? ?? 0,
  );
}
