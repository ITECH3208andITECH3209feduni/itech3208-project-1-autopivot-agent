/// Mirrors `BackdropOut` in `api/schemas.py` — one entry in a dealership's
/// backdrop library, picked when queuing a listing for processing.
library;

class Backdrop {
  const Backdrop({
    required this.id,
    required this.name,
    required this.isDefault,
    required this.imageUrl,
  });

  final int id;
  final String name;

  /// Shown first in a picker, and pre-selected — a dealership with a house
  /// backdrop should not need to pick it every time.
  final bool isDefault;

  /// Path to fetch via `ApiClient.fileBytes` / the `AuthedImage` widget, the
  /// same as a listing photograph — this is not a plain, unauthenticated URL.
  final String imageUrl;

  factory Backdrop.fromJson(Map<String, dynamic> json) => Backdrop(
    id: json['id'] as int,
    name: json['name'] as String,
    isDefault: json['is_default'] as bool? ?? false,
    imageUrl: json['image_url'] as String,
  );
}
