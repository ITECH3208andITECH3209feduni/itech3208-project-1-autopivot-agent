/// Mirrors `ImageOut` in `api/schemas.py`.
library;

class ListingImage {
  const ListingImage({
    required this.id,
    required this.imageType,
    required this.sourceImageId,
    required this.imageKind,
    required this.kindConfidence,
    required this.originalFilename,
    required this.imageUrl,
    required this.width,
    required this.height,
    required this.fileSizeBytes,
    required this.createdAt,
  });

  final int id;

  /// One of 'original', 'processed', 'background', 'plate_overlay'.
  final String imageType;

  /// The original this one was made from, so a processed result can be
  /// paired with its before shot without fetching the processing jobs too.
  /// Null on an original, and on anything processed before this column
  /// existed.
  final int? sourceImageId;

  /// What the photograph is of: 'exterior', 'interior', 'detail',
  /// 'advertisement', 'unknown', or null if nothing has classified it yet.
  /// A separate axis from [imageType] — this describes the subject, not the
  /// pipeline stage.
  final String? imageKind;
  final double? kindConfidence;

  final String originalFilename;

  /// Path to fetch via `ApiClient.fileBytes` / the `AuthedImage` widget — the
  /// endpoint requires the bearer header, so this is never loadable as a
  /// plain URL.
  final String imageUrl;

  final int width;
  final int height;
  final int fileSizeBytes;
  final DateTime createdAt;

  bool get isOriginal => imageType == 'original';
  bool get isProcessed => imageType == 'processed';

  /// True when the classifier looked at this photograph and decided it was
  /// not usable — an advertisement, an interior shot, a close-up of a part.
  /// Null (not yet classified) is deliberately not excluded: excluding
  /// something the classifier has not actually judged would misrepresent
  /// what happened to it.
  bool get isExcluded => imageKind != null && imageKind != 'exterior';

  factory ListingImage.fromJson(Map<String, dynamic> json) => ListingImage(
    id: json['id'] as int,
    imageType: json['image_type'] as String,
    sourceImageId: json['source_image_id'] as int?,
    imageKind: json['image_kind'] as String?,
    kindConfidence: (json['kind_confidence'] as num?)?.toDouble(),
    originalFilename: json['original_filename'] as String,
    imageUrl: json['image_url'] as String,
    width: json['width'] as int,
    height: json['height'] as int,
    fileSizeBytes: json['file_size_bytes'] as int,
    createdAt: DateTime.parse(json['created_at'] as String),
  );
}
