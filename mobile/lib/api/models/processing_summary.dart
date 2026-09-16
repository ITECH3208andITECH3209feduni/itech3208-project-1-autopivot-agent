/// Mirrors `ProcessingSummary` in `api/schemas.py` — the counts the
/// Processing screen polls, not the full per-photograph job detail.
///
/// [ProcessingJobOut] is deliberately not modelled here: the images a client
/// needs to actually show (originals, processed, which is excluded and why)
/// already come from `VehicleListingDetail.images`, which every job read
/// would otherwise duplicate. This carries only what that response cannot
/// answer — is the pipeline still running, and how far has it got.
library;

class ProcessingSummary {
  const ProcessingSummary({
    required this.listingId,
    required this.processingStatus,
    required this.total,
    required this.completed,
    required this.failed,
    required this.needsReview,
  });

  final int listingId;

  /// One of 'pending', 'processing', 'complete', 'needs_review'.
  final String processingStatus;

  final int total;
  final int completed;
  final int failed;
  final int needsReview;

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
      );
}
