// Sending a capture set to the server:
// lib/features/capture/capture_submission.dart.
//
// _Server stands in for ApiClient and answers the calls a submit makes the way
// api/routes_listings.py does, including the two properties the retry rules
// exist for: an upload commits all of its photographs or none of them, and a
// photograph's bytes can be stored only once (storage paths are content
// hashes and globally unique), so bytes already on any listing are refused
// with a 409. What it hands back is parsed from the server's own JSON shapes
// by the real model classes, and it throws what the real client throws.
//
// Plain test() rather than testWidgets(): the photographs are real files, and
// real file I/O never completes inside testWidgets' FakeAsync zone.
//
// The last group carries a failed attempt across the camera closing, through
// the real draft store (lib/features/capture/capture_draft.dart), with
// path_provider answered on its method channel as capture_draft_test.dart
// does.

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/api/api_exception.dart';
import 'package:autopivot/api/models/listing_detail.dart';
import 'package:autopivot/api/models/listing_image.dart';
import 'package:autopivot/api/models/processing_summary.dart';
import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/capture_draft.dart';
import 'package:autopivot/features/capture/capture_submission.dart';
import 'package:autopivot/features/capture/review_screen.dart';

const _cx5 = VehicleDetails(make: 'Mazda', model: 'CX-5', year: 2021);
const _timestamp = '2026-09-25T09:00:00';
const _pathProvider = MethodChannel('plugins.flutter.io/path_provider');

class _Photo {
  _Photo(this.id, this.filename, this.bytes);

  final int id;
  final String filename;
  final String bytes;
}

class _Listing {
  _Listing(this.id, this.make, this.model, this.year, this.variant);

  final int id;
  final String make;
  final String model;
  final int year;
  final String? variant;
  final photos = <_Photo>[];

  /// `_title_for` in routes_listings.py.
  String get title => [
    year,
    make,
    model,
    variant,
  ].where((part) => part != null && '$part'.isNotEmpty).join(' ');
}

class _Server extends ApiClient {
  _Server() : super(baseUrl: 'http://autopivot.invalid');

  final listingsById = <int, _Listing>{};

  /// Listing ids processing was queued for, in order.
  final processed = <int>[];

  var _lastListingId = 0;
  var _lastImageId = 0;

  /// The next upload is stored, but its reply never arrives: lot Wi-Fi
  /// dropping out, the app backgrounded, the 30-second receive timeout.
  bool loseNextUploadReply = false;

  /// The next upload never reaches the server at all.
  bool dropNextUpload = false;

  /// Uploads go through the real ApiClient.uploadImages instead, for its own
  /// handling of the files it is handed.
  bool realUploads = false;

  /// Processing refused, as by a server without the vision stack (a 503,
  /// which the real client reports as ApiServerException).
  bool processingUnavailable = false;

  List<String> photosOn(int listingId) => [
    for (final photo in listingsById[listingId]!.photos) photo.filename,
  ];

  _Listing _find(int listingId) =>
      listingsById[listingId] ??
      (throw const ApiRequestException('Listing not found.', statusCode: 404));

  @override
  Future<VehicleListingDetail> createListing({
    required String make,
    required String model,
    required int year,
    String? variant,
  }) async {
    final listing = _Listing(++_lastListingId, make, model, year, variant);
    listingsById[listing.id] = listing;
    return _detail(listing);
  }

  @override
  Future<VehicleListingDetail> listing(int listingId) async =>
      _detail(_find(listingId));

  @override
  Future<List<ListingImage>> uploadImages(
    int listingId,
    List<String> filePaths,
  ) async {
    if (realUploads) return super.uploadImages(listingId, filePaths);
    if (dropNextUpload) {
      dropNextUpload = false;
      throw const ApiNetworkException();
    }

    final listing = _find(listingId);
    final incoming = [
      for (final path in filePaths)
        (filename: path.split('/').last, bytes: await File(path).readAsString()),
    ];
    final stored = {
      for (final other in listingsById.values)
        for (final photo in other.photos) photo.bytes,
    };
    if (incoming.any((photo) => stored.contains(photo.bytes))) {
      throw const ApiRequestException(
        'One of those photographs has already been uploaded.',
        statusCode: 409,
      );
    }

    final added = [
      for (final photo in incoming)
        _Photo(++_lastImageId, photo.filename, photo.bytes),
    ];
    listing.photos.addAll(added);
    if (loseNextUploadReply) {
      loseNextUploadReply = false;
      throw const ApiNetworkException(
        'AutoPivot took too long to respond. Please try again.',
      );
    }
    return [for (final photo in added) ListingImage.fromJson(_image(photo))];
  }

  @override
  Future<ProcessingSummary> processListing(
    int listingId, {
    int? backdropId,
  }) async {
    final listing = _find(listingId);
    if (processingUnavailable) throw const ApiServerException();
    if (listing.photos.isEmpty) {
      throw const ApiRequestException(
        'There is nothing to process — every photograph is already done.',
        statusCode: 400,
      );
    }
    processed.add(listingId);
    return ProcessingSummary.fromJson({
      'listing_id': listingId,
      'processing_status': 'processing',
      'total': listing.photos.length,
      'completed': 0,
      'failed': 0,
      'needs_review': 0,
      'jobs': <Object>[],
    });
  }

  @override
  Future<void> deleteListing(int listingId) async {
    _find(listingId);
    listingsById.remove(listingId);
  }

  VehicleListingDetail _detail(_Listing listing) =>
      VehicleListingDetail.fromJson({
        'id': listing.id,
        'stock_number': null,
        'title': listing.title,
        'make': listing.make,
        'model': listing.model,
        'year': listing.year,
        'variant': listing.variant,
        'price': null,
        'status': 'draft',
        'processing_status': 'pending',
        'image_count': listing.photos.length,
        'created_at': _timestamp,
        'updated_at': _timestamp,
        'description': null,
        'images': [for (final photo in listing.photos) _image(photo)],
      });

  Map<String, dynamic> _image(_Photo photo) => {
    'id': photo.id,
    'image_type': 'original',
    'source_image_id': null,
    'image_kind': null,
    'kind_confidence': null,
    'original_filename': photo.filename,
    'image_url': '/api/files/1/original/photo-${photo.id}.jpg',
    'width': 4032,
    'height': 3024,
    'file_size_bytes': photo.bytes.length,
    'created_at': _timestamp,
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory camera;

  setUp(() async {
    camera = await Directory.systemTemp.createTemp('submission_camera_');
  });

  tearDown(() => camera.delete(recursive: true));

  /// A shot as the camera plugin leaves it: a file of its own in a temporary
  /// directory. [contents] stands in for the image bytes.
  Future<String> shot(String name, String contents) async {
    final file = File('${camera.path}/$name.jpg');
    await file.writeAsString(contents);
    return file.path;
  }

  test('a retry after the photographs arrived but the reply did not '
      'processes that same listing', () async {
    final server = _Server();
    final submission = CaptureSubmission();
    final photos = [await shot('CAP_1', 'front'), await shot('CAP_2', 'rear')];

    server.loseNextUploadReply = true;
    expect(
      await submission.submit(api: server, details: _cx5, photoPaths: photos),
      isA<SubmitFailed>(),
    );

    final retry = await submission.submit(
      api: server,
      details: _cx5,
      photoPaths: photos,
    );

    expect(retry, isA<Submitted>());
    expect(server.listingsById.keys, [1]);
    expect(server.photosOn(1), ['CAP_1.jpg', 'CAP_2.jpg']);
    expect(server.processed, [1]);
  });

  test('a retry after the upload never arrived sends it to the listing '
      'already created', () async {
    final server = _Server();
    final submission = CaptureSubmission();
    final photos = [await shot('CAP_1', 'front'), await shot('CAP_2', 'rear')];

    server.dropNextUpload = true;
    expect(
      await submission.submit(api: server, details: _cx5, photoPaths: photos),
      isA<SubmitFailed>(),
    );

    final retry = await submission.submit(
      api: server,
      details: _cx5,
      photoPaths: photos,
    );

    expect(server.listingsById.keys, [1]);
    expect(retry, isA<Submitted>());
    expect(server.photosOn(1), ['CAP_1.jpg', 'CAP_2.jpg']);
    expect(server.processed, [1]);
  });

  test('a set changed before the retry replaces the listing the failed '
      'attempt left', () async {
    final server = _Server();
    final submission = CaptureSubmission();
    final front = await shot('CAP_1', 'front');
    final rear = await shot('CAP_2', 'rear');
    final rearReshot = await shot('CAP_3', 'rear, reshot');

    server.loseNextUploadReply = true;
    await submission.submit(api: server, details: _cx5, photoPaths: [front, rear]);

    final retry = await submission.submit(
      api: server,
      details: _cx5,
      photoPaths: [front, rearReshot],
    );

    expect(retry, isA<Submitted>());
    expect(server.listingsById.keys, [2]);
    expect(server.photosOn(2), ['CAP_1.jpg', 'CAP_3.jpg']);
    expect(server.processed, [2]);
  });

  test('corrected vehicle details replace the listing the failed attempt '
      'created', () async {
    final server = _Server();
    final submission = CaptureSubmission();
    final photos = [await shot('CAP_1', 'front'), await shot('CAP_2', 'rear')];

    server.loseNextUploadReply = true;
    await submission.submit(
      api: server,
      details: const VehicleDetails(make: 'Mazda', model: 'CX-3', year: 2021),
      photoPaths: photos,
    );

    final retry = await submission.submit(
      api: server,
      details: _cx5,
      photoPaths: photos,
    );

    expect(retry, isA<Submitted>());
    expect(server.listingsById.keys, [2]);
    expect(server.listingsById[2]!.model, 'CX-5');
    expect(server.photosOn(2), ['CAP_1.jpg', 'CAP_2.jpg']);
    expect(server.processed, [2]);
  });

  test('a listing deleted since the failed attempt is replaced rather than '
      'retried forever', () async {
    final server = _Server();
    final submission = CaptureSubmission();
    final photos = [await shot('CAP_1', 'front')];

    server.dropNextUpload = true;
    await submission.submit(api: server, details: _cx5, photoPaths: photos);
    // Removed on the platform in the meantime, say.
    await server.deleteListing(1);

    final retry = await submission.submit(
      api: server,
      details: _cx5,
      photoPaths: photos,
    );

    expect(retry, isA<Submitted>());
    expect(server.listingsById.keys, [2]);
    expect(server.processed, [2]);
  });

  test('a photograph no longer on the phone fails the attempt with a '
      'message instead of escaping', () async {
    final server = _Server()..realUploads = true;
    final gone = '${camera.path}/CAP_1.jpg';

    await expectLater(
      CaptureSubmission().submit(api: server, details: _cx5, photoPaths: [gone]),
      completion(isA<SubmitFailed>()),
    );
  });

  test('processing that cannot be started still counts as submitted, with '
      'the reason', () async {
    final server = _Server()..processingUnavailable = true;

    final result = await CaptureSubmission().submit(
      api: server,
      details: _cx5,
      photoPaths: [await shot('CAP_1', 'front')],
    );

    expect(
      result,
      isA<Submitted>().having(
        (submitted) => submitted.processingWarning,
        'processingWarning',
        'AutoPivot had a problem. Please try again shortly.',
      ),
    );
    expect(server.photosOn(1), ['CAP_1.jpg']);
  });

  group('once the camera has closed on a failed attempt', () {
    late Directory documents;

    setUp(() async {
      documents = await Directory.systemTemp.createTemp('submission_documents_');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(_pathProvider, (call) async => documents.path);
    });

    tearDown(() async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(_pathProvider, null);
      await documents.delete(recursive: true);
    });

    /// A new capture screen opened over the draft [saved] with, and resumed
    /// the way CaptureScreen resumes one: a new submission picking up the
    /// attempt the draft kept, and the photographs now the draft's own copies,
    /// in sequence order.
    Future<(CaptureSubmission, List<String>)> resumeDraft(
      CaptureSubmission saved,
      Map<CaptureAngle, String> capturedPaths,
    ) async {
      await saveCaptureDraft(
        capturedPaths: capturedPaths,
        skipped: {},
        unfinishedSubmission: saved.unfinished,
      );
      final draft = (await loadCaptureDraft())!;
      final resumed = CaptureSubmission();
      if (draft.unfinishedSubmission case final attempt?) {
        resumed.resume(attempt);
      }
      return (
        resumed,
        [
          for (final angle in CaptureAngle.values)
            if (draft.files[angle] case final file?) file.path,
        ],
      );
    }

    test('a retry of the resumed set processes the listing its photographs '
        'already reached', () async {
      final server = _Server();
      final failed = CaptureSubmission();
      final captured = {
        CaptureAngle.front: await shot('CAP_1', 'front'),
        CaptureAngle.rear: await shot('CAP_2', 'rear'),
      };

      server.loseNextUploadReply = true;
      expect(
        await failed.submit(
          api: server,
          details: _cx5,
          photoPaths: captured.values.toList(),
        ),
        isA<SubmitFailed>(),
      );

      final (resumed, photos) = await resumeDraft(failed, captured);
      final retry = await resumed.submit(
        api: server,
        details: _cx5,
        photoPaths: photos,
      );

      expect(retry, isA<Submitted>());
      expect(server.listingsById.keys, [1]);
      expect(server.photosOn(1), ['CAP_1.jpg', 'CAP_2.jpg']);
      expect(server.processed, [1]);
    });

    test('a retry of the resumed set sends an upload that never arrived to '
        'the listing already created', () async {
      final server = _Server();
      final failed = CaptureSubmission();
      final captured = {
        CaptureAngle.front: await shot('CAP_1', 'front'),
        CaptureAngle.rear: await shot('CAP_2', 'rear'),
      };

      server.dropNextUpload = true;
      expect(
        await failed.submit(
          api: server,
          details: _cx5,
          photoPaths: captured.values.toList(),
        ),
        isA<SubmitFailed>(),
      );

      final (resumed, photos) = await resumeDraft(failed, captured);
      final retry = await resumed.submit(
        api: server,
        details: _cx5,
        photoPaths: photos,
      );

      expect(retry, isA<Submitted>());
      expect(server.listingsById.keys, [1]);
      expect(server.photosOn(1), ['CAP_1.jpg', 'CAP_2.jpg']);
      expect(server.processed, [1]);
    });

    test('a photograph retaken after resuming replaces the listing, even '
        'once the draft has been resumed again', () async {
      final server = _Server();
      final failed = CaptureSubmission();
      final captured = {
        CaptureAngle.front: await shot('CAP_1', 'front'),
        CaptureAngle.rear: await shot('CAP_2', 'rear'),
      };

      server.loseNextUploadReply = true;
      await failed.submit(
        api: server,
        details: _cx5,
        photoPaths: captured.values.toList(),
      );
      final (resumed, photos) = await resumeDraft(failed, captured);

      // The rear is shot again, which saves the draft again, and the camera
      // closes once more before the set is sent.
      final (resumedAgain, photosNow) = await resumeDraft(resumed, {
        CaptureAngle.front: photos.first,
        CaptureAngle.rear: await shot('CAP_3', 'rear, reshot'),
      });
      final retry = await resumedAgain.submit(
        api: server,
        details: _cx5,
        photoPaths: photosNow,
      );

      expect(retry, isA<Submitted>());
      expect(server.listingsById.keys, [2]);
      expect(server.photosOn(2), ['CAP_1.jpg', 'CAP_3.jpg']);
      expect(server.processed, [2]);
    });
  });
}
