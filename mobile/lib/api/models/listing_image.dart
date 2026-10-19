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
    required this.keptWithoutProcessing,
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

  /// A dealer's permanent opt-out of the pipeline for this one original —
  /// set by the include endpoint's 'keep_only' mode for a photograph that
  /// should stay visible as a normal original (an interior shot, say)
  /// without ever being cut out and composited. Deliberately independent of
  /// [imageKind]: that stays whatever the classifier decided, so the record
  /// of what the photograph actually is survives a dealer's decision to show
  /// it anyway.
  final bool keptWithoutProcessing;

  bool get isOriginal => imageType == 'original';
  bool get isProcessed => imageType == 'processed';

  /// True when the classifier looked at this photograph and decided it was
  /// not usable — an advertisement, an interior shot, a close-up of a part —
  /// and nobody has since asked for it to be kept as-is anyway. Null (not
  /// yet classified) is deliberately not excluded: excluding something the
  /// classifier has not actually judged would misrepresent what happened to
  /// it. [keptWithoutProcessing] overrides this regardless of [imageKind],
  /// because it is a dealer's explicit "show it as a normal photograph", not
  /// a change of mind about what the photograph is of.
  bool get isExcluded =>
      imageKind != null && imageKind != 'exterior' && !keptWithoutProcessing;

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
    // Absent on a server from before this column existed — false is the
    // same "nothing has opted this out" reading as everywhere else in this
    // file that defaults rather than requires a key that may not exist yet.
    keptWithoutProcessing: json['kept_without_processing'] as bool? ?? false,
  );
}
