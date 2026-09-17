/// Mirrors `ProcessingSummary` in `api/schemas.py` — the counts the
/// Processing screen polls, plus [jobs] for the one thing the counts alone
/// cannot answer: *why* a specific photograph needs a person to look at it.
///
/// [jobs] used to be left unmodelled entirely, on the reasoning that a
/// client's images already say which are excluded and why. That covers the
/// classifier's own exclusions (advertisement, interior, close-up) but not a
/// job whose review_state is 'needs_review' because no vehicle was found at
/// all — that reason (`ProcessingJobOut.error_message`) lives only on the
/// job, and a photograph in that state has no processed counterpart for
/// `VehicleListingDetail.images` to explain anything through. Modelled now
/// so `listing_detail_screen.dart` can show that reason instead of leaving
/// the photograph sitting in an unexplained "awaiting processing" bucket.
library;

class ProcessingJobSummary {
  const ProcessingJobSummary({
    required this.inputImageId,
    required this.status,
    required this.reviewState,
    required this.errorMessage,
    required this.backdropId,
  });

  final int inputImageId;

  /// One of 'pending', 'processing', 'completed', 'failed'.
  final String status;

  /// Null until the job finishes; 'ok' or 'needs_review' once it does.
  final String? reviewState;

  /// Set on a 'failed' job, and on a 'completed' one whose reviewState is
  /// 'needs_review' — explains what happened either way, in a sentence
  /// that is already safe to show a dealer as-is.
  final String? errorMessage;

  /// The backdrop this attempt ran with, if any — carried along so a retry
  /// started from this job can reuse the same choice instead of falling
  /// back to a transparent background.
  final int? backdropId;

  factory ProcessingJobSummary.fromJson(Map<String, dynamic> json) =>
      ProcessingJobSummary(
        inputImageId: json['input_image_id'] as int,
        status: json['status'] as String,
        reviewState: json['review_state'] as String?,
        errorMessage: json['error_message'] as String?,
        backdropId: json['backdrop_id'] as int?,
      );
}

class ProcessingSummary {
  const ProcessingSummary({
    required this.listingId,
    required this.processingStatus,
    required this.total,
    required this.completed,
    required this.failed,
    required this.needsReview,
    required this.jobs,
  });

  final int listingId;

  /// One of 'pending', 'processing', 'complete', 'needs_review'.
  final String processingStatus;

  final int total;
  final int completed;
  final int failed;
  final int needsReview;
  final List<ProcessingJobSummary> jobs;

  /// True while there is still work the pipeline could be doing — the signal
  /// a poller uses to decide whether to keep asking.
  bool get isInProgress =>
      processingStatus == 'pending' || processingStatus == 'processing';

  factory ProcessingSummary.fromJson(Map<String, dynamic> json) =>
      ProcessingSummary(
        listingId: json['listing_id'] as int,
        processingStatus: json['processing_status'] as String,
        total: json['total'] as int? ?? 0,
        completed: json['completed'] as int? ?? 0,
        failed: json['failed'] as int? ?? 0,
        needsReview: json['needs_review'] as int? ?? 0,
        jobs: (json['jobs'] as List<dynamic>? ?? [])
            .map((e) => ProcessingJobSummary.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
