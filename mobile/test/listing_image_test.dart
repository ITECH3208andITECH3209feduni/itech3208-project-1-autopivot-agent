// Unit tests for `ListingImage`'s own derived state — see
// lib/api/models/listing_image.dart. No widget to pump, so these are plain
// test() rather than testWidgets(), the same reasoning
// capture_submission_test.dart gives for its own plain tests.

import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/models/listing_image.dart';

const _at = '2026-09-25T09:00:00';

/// `ImageOut`, with `kept_without_processing` left out of the map entirely
/// when [keptWithoutProcessing] is null — a server from before that column
/// existed sends exactly this shape.
Map<String, Object?> _image({String? imageKind, bool? keptWithoutProcessing}) => {
  'id': 11,
  'image_type': 'original',
  'source_image_id': null,
  'image_kind': imageKind,
  'kind_confidence': imageKind == null ? null : 0.9,
  'original_filename': 'IMG_11.jpg',
  'image_url': '/api/files/3/original/11.jpg',
  'width': 4032,
  'height': 3024,
  'file_size_bytes': 2400000,
  'created_at': _at,
  'kept_without_processing': ?keptWithoutProcessing,
};

void main() {
  group('ListingImage.isExcluded', () {
    test('is false for an original nothing has classified yet', () {
      expect(ListingImage.fromJson(_image()).isExcluded, isFalse);
    });

    test('is false for an exterior photograph', () {
      expect(
        ListingImage.fromJson(_image(imageKind: 'exterior')).isExcluded,
        isFalse,
      );
    });

    test('is true for a photograph the classifier left out', () {
      expect(
        ListingImage.fromJson(_image(imageKind: 'interior')).isExcluded,
        isTrue,
      );
    });

    test(
      'is false once kept_without_processing overrides a non-exterior kind',
      () {
        expect(
          ListingImage.fromJson(
            _image(imageKind: 'interior', keptWithoutProcessing: true),
          ).isExcluded,
          isFalse,
        );
      },
    );

    test('kept_without_processing false still leaves a non-exterior kind excluded', () {
      expect(
        ListingImage.fromJson(
          _image(imageKind: 'advertisement', keptWithoutProcessing: false),
        ).isExcluded,
        isTrue,
      );
    });

    test('defaults kept_without_processing to false when the server omits it', () {
      // A server from before this column existed — isExcluded must read the
      // same as it always has, not crash on a missing key.
      expect(
        ListingImage.fromJson(_image(imageKind: 'detail')).isExcluded,
        isTrue,
      );
    });
  });

  group('ListingImage.fromJson', () {
    test('reads kept_without_processing back', () {
      final image = ListingImage.fromJson(
        _image(imageKind: 'interior', keptWithoutProcessing: true),
      );
      expect(image.keptWithoutProcessing, isTrue);
    });
  });
}
