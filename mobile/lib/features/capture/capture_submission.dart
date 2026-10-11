/// Sends a finished capture set to the server: creates its listing, uploads
/// every photograph and queues them for processing.
///
/// Its own file, away from [CaptureScreen], so the sequence can be tested
/// against a stand-in [ApiClient] without the camera screen around it.
library;

import 'dart:io' show FileSystemException;

import '../../api/api_client.dart';
import '../../api/api_exception.dart';
import '../../api/models/listing_detail.dart';
import 'review_screen.dart' show VehicleDetails;

/// How one attempt at [CaptureSubmission.submit] ended.
sealed class SubmitResult {
  const SubmitResult();
}

/// The listing exists with every photograph on it.
final class Submitted extends SubmitResult {
  const Submitted({
    required this.listingTitle,
    required this.photoCount,
    this.processingWarning,
  });

  final String listingTitle;
  final int photoCount;

  /// Why processing could not be queued, when it could not. The listing and
  /// its photographs exist either way, so this is a warning on a finished
  /// submit rather than a failed one.
  final String? processingWarning;
}

/// The attempt stopped short; [message] is safe to show as-is.
final class SubmitFailed extends SubmitResult {
  const SubmitFailed(this.message);

  final String message;

  @override
  String toString() => 'SubmitFailed: $message';
}

/// One capture set's way to the server, kept for as long as the capture
/// screen is open so that a failed attempt can be retried without starting
/// over — see [submit] — and, through the draft, past it: see [unfinished].
class CaptureSubmission {
  /// The listing an earlier attempt created without seeing it through to
  /// processing, and what that attempt was for. Null before the first
  /// attempt, and again once one finishes.
  UnfinishedSubmission? _unfinished;

  /// That attempt, for as long as it is unfinished: what the capture draft
  /// keeps with its photographs (see capture_draft.dart) so that it outlives
  /// this object, for [resume] to take back.
  ///
  /// Kept only in memory, it went with the screen, closed after the failure
  /// with Save Draft or without, or the app killed, and a retry of the
  /// resumed draft then made a second listing, whose upload was refused with
  /// a 409 because the photographs had already reached the first one, which
  /// nothing would ever queue.
  UnfinishedSubmission? get unfinished => _unfinished;

  /// Carries on with [attempt], one an earlier screen left unfinished (see
  /// [unfinished]), exactly as though it had been made here: the next
  /// [submit] of the same set reuses its listing.
  void resume(UnfinishedSubmission attempt) => _unfinished = attempt;

  /// Creates the listing, uploads [photoPaths] to it and queues it for
  /// processing — or, after an attempt that failed part-way, carries on from
  /// where that one stopped.
  ///
  /// An attempt can fail after the server has already done its part: the
  /// upload stored, then its reply lost to lot Wi-Fi, a backgrounded app or
  /// the 30-second receive timeout. Starting over from the top is what used
  /// to make every retry add another, empty listing whose upload was refused
  /// with a 409 (the server stores a photograph's bytes only once), while the
  /// listing actually holding the photographs was never queued. So a retry of
  /// the same submission — the same vehicle details and the same photographs
  /// — reuses that attempt's listing, asks the server what it now holds, and
  /// uploads only what it is missing: after a lost reply, nothing, and on
  /// straight to processing. An upload is all or nothing server-side, so
  /// "missing" is every photograph or none of them.
  ///
  /// A retry after the photographer changed anything in between (a retake, a
  /// photograph added or removed, a corrected make or model) is a different
  /// submission: the listing the failed attempt created is deleted, and this
  /// one starts over with a new listing. Deleted rather than topped up,
  /// because [ApiClient] can't correct a listing's make, model or year (only
  /// its status), and because a new listing can't be given photographs the
  /// old one still holds; those bytes would be refused as duplicates. The
  /// old listing is this screen's own, was never processed, and as far as
  /// the photographer knows was never made. The cost is sending again
  /// whatever it already held, only when a set changes after a lost reply.
  ///
  /// Never throws: any failure, not only an [ApiException], comes back as
  /// [SubmitFailed].
  Future<SubmitResult> submit({
    required ApiClient api,
    required VehicleDetails details,
    required List<String> photoPaths,
    int? backdropId,
  }) async {
    try {
      final (listing, onServer) = await _listingFor(api, details, photoPaths);
      final missing = [
        for (final path in photoPaths)
          if (!onServer.contains(_fileName(path))) path,
      ];
      if (missing.isNotEmpty) await api.uploadImages(listing.id, missing);

      // A processing failure here does not undo the upload above — the
      // photographs and the listing both exist either way, which is why
      // this is its own try block with its own message rather than folding
      // into the outer catch and implying the whole submit failed.
      String? processingWarning;
      try {
        await api.processListing(listing.id, backdropId: backdropId);
      } on ApiException catch (e) {
        processingWarning = e.message;
      } catch (_) {
        processingWarning = _unexpectedFailure;
      }
      _unfinished = null;
      return Submitted(
        listingTitle: listing.title,
        photoCount: photoPaths.length,
        processingWarning: processingWarning,
      );
    } on ApiException catch (e) {
      return SubmitFailed(e.message);
    } on FileSystemException {
      return const SubmitFailed(
        'A photograph in this set could not be read from the phone, so the '
        'set was not sent. Retake it, then submit again.',
      );
    } catch (_) {
      return const SubmitFailed(_unexpectedFailure);
    }
  }

  /// The listing this attempt goes to, with the file names of the
  /// photographs already on it.
  Future<(VehicleListingDetail, Set<String>)> _listingFor(
    ApiClient api,
    VehicleDetails details,
    List<String> photoPaths,
  ) async {
    final unfinished = _unfinished;
    if (unfinished != null) {
      if (unfinished._isFor(details, photoPaths)) {
        final current = await _stillThere(api, unfinished.listingId);
        if (current != null) {
          return (
            current,
            {for (final image in current.originals) image.originalFilename},
          );
        }
      } else {
        await _delete(api, unfinished.listingId);
      }
      _unfinished = null;
    }

    final created = await api.createListing(
      make: details.make,
      model: details.model,
      year: details.year,
      variant: details.variant,
    );
    _unfinished = UnfinishedSubmission._(
      listingId: created.id,
      details: details,
      photos: {for (final path in photoPaths) _fileName(path)},
    );
    return (created, const <String>{});
  }

  /// The listing as the server has it now, or null once it has been deleted
  /// (on the platform, say): a 404 that retrying against it would only
  /// repeat for good.
  Future<VehicleListingDetail?> _stillThere(ApiClient api, int listingId) async {
    try {
      return await api.listing(listingId);
    } on ApiRequestException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<void> _delete(ApiClient api, int listingId) async {
    try {
      await api.deleteListing(listingId);
    } on ApiRequestException catch (e) {
      // Already gone: deleted on the platform, or by an earlier attempt of
      // this whose reply was lost.
      if (e.statusCode != 404) rethrow;
    }
  }
}

const _unexpectedFailure =
    'Something went wrong on this phone. Please try again.';

/// The name the server files a photograph under: the upload's own file name,
/// which dio sets to the last segment of its path.
String _fileName(String path) => path.substring(path.lastIndexOf('/') + 1);

/// A listing a submit created and never saw through to processing, and what
/// it was created for: everything a retry needs to carry on with that
/// listing instead of making another — see [CaptureSubmission.submit].
///
/// Photographs are known by the name the server files each one under (see
/// [_fileName]), not by where the file is. That name is what the server can
/// be asked about, and it is what survives a draft copying a photograph into
/// the app's own storage (see capture_draft.dart): a new path, the same name.
/// The camera writes every shot under a name of its own, so a retaken angle
/// is a new name, and a different set.
final class UnfinishedSubmission {
  UnfinishedSubmission._({
    required this.listingId,
    required this.details,
    required Set<String> photos,
  }) : photos = Set.unmodifiable(photos);

  final int listingId;
  final VehicleDetails details;

  /// The file names of the photographs the attempt was for.
  final Set<String> photos;

  bool _isFor(VehicleDetails other, List<String> photoPaths) {
    final names = {for (final path in photoPaths) _fileName(path)};
    return other.make == details.make &&
        other.model == details.model &&
        other.year == details.year &&
        other.variant == details.variant &&
        names.length == photos.length &&
        photos.containsAll(names);
  }

  Map<String, Object?> toJson() => {
    'listing_id': listingId,
    'make': details.make,
    'model': details.model,
    'year': details.year,
    'variant': details.variant,
    'photos': photos.toList(),
  };

  /// What [toJson] wrote, read back; null for anything else. A damaged
  /// record costs only what these exist to prevent, a retry that makes a
  /// second listing (refused with a 409 if the photographs had reached the
  /// first), where throwing would cost the draft holding it every photograph
  /// in it.
  static UnfinishedSubmission? fromJson(Object? json) {
    if (json is! Map<String, Object?>) return null;
    final listingId = json['listing_id'];
    final make = json['make'];
    final model = json['model'];
    final year = json['year'];
    final variant = json['variant'];
    final photos = json['photos'];
    if (listingId is! int ||
        make is! String ||
        model is! String ||
        year is! int ||
        variant is! String? ||
        photos is! List<Object?> ||
        !photos.every((name) => name is String)) {
      return null;
    }
    return UnfinishedSubmission._(
      listingId: listingId,
      details: VehicleDetails(
        make: make,
        model: model,
        year: year,
        variant: variant,
      ),
      photos: {...photos.cast<String>()},
    );
  }
}
