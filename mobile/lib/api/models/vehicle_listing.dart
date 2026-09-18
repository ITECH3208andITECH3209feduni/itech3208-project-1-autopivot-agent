/// Mirrors `VehicleListingOut` in `api/schemas.py`.
library;

class VehicleListing {
  const VehicleListing({
    required this.id,
    required this.stockNumber,
    required this.title,
    required this.make,
    required this.model,
    required this.year,
    required this.variant,
    required this.price,
    required this.status,
    required this.processingStatus,
    required this.imageCount,
    required this.createdAt,
    required this.updatedAt,
  });

  final int id;
  final String? stockNumber;

  /// Derived server-side, e.g. "2021 Mazda CX-5 GT". Not assembled here, so the
  /// two clients cannot disagree about how a vehicle is named.
  final String title;

  final String make;
  final String model;
  final int year;
  final String? variant;

  /// Held as a string, never a double.
  ///
  /// The server sends a SQL `NUMERIC`. Parsing money into a binary float is how
  /// a price becomes 24999.999999997, and nothing here needs to do arithmetic
  /// on it — only display it.
  final String? price;

  /// Where the vehicle is in the sales cycle: draft, active, sold, archived.
  final String status;

  /// Where its photographs are in the pipeline: pending, processing, complete,
  /// needs_review.
  ///
  /// A separate axis from [status] on purpose — a vehicle can be sold while its
  /// photographs are still awaiting review. Do not conflate the two.
  final String processingStatus;

  final int imageCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory VehicleListing.fromJson(Map<String, dynamic> json) => VehicleListing(
    id: json['id'] as int,
    stockNumber: json['stock_number'] as String?,
    title: json['title'] as String,
    make: json['make'] as String,
    model: json['model'] as String,
    year: json['year'] as int,
    variant: json['variant'] as String?,
    // Accepts whichever wire form the server uses: pydantic may serialise a
    // Decimal as a JSON string or a number depending on its configuration, and
    // both land here as a string without passing through a float.
    price: json['price']?.toString(),
    status: json['status'] as String,
    processingStatus: json['processing_status'] as String,
    imageCount: json['image_count'] as int? ?? 0,
    createdAt: DateTime.parse(json['created_at'] as String),
    updatedAt: DateTime.parse(json['updated_at'] as String),
  );
}
