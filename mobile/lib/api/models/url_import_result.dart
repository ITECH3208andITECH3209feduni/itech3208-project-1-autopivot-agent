/// Mirrors `UrlImportResult` in `api/schemas.py` — what importing
/// photographs from a pasted listing URL onto an existing listing returns.
library;

import 'listing_image.dart';

class UrlImportResult {
  const UrlImportResult({required this.images, this.note});

  final List<ListingImage> images;

  /// Set when the import worked but is worth a second look — a page serves
  /// whatever it published, logos and banners included.
  final String? note;

  factory UrlImportResult.fromJson(Map<String, dynamic> json) =>
      UrlImportResult(
        images: (json['images'] as List<dynamic>? ?? [])
            .map((e) => ListingImage.fromJson(e as Map<String, dynamic>))
            .toList(),
        note: json['note'] as String?,
      );
}
