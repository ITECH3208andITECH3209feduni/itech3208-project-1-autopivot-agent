/// Mirrors `DashboardStats` in `api/schemas.py`, served by
/// `/api/dashboard/stats` — scoped to the current calendar month, unlike
/// [NavCounts]' all-time totals, which is why the two are separate models
/// rather than one shared shape.
library;

class DashboardStats {
  const DashboardStats({
    required this.vehiclesThisMonth,
    required this.imagesProcessed,
    required this.needsReview,
  });

  final int vehiclesThisMonth;
  final int imagesProcessed;
  final int needsReview;

  factory DashboardStats.fromJson(Map<String, dynamic> json) => DashboardStats(
    vehiclesThisMonth: json['vehicles_this_month'] as int? ?? 0,
    imagesProcessed: json['images_processed'] as int? ?? 0,
    needsReview: json['needs_review'] as int? ?? 0,
  );
}
