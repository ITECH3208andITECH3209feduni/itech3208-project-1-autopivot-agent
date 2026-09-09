/// Mirrors `VehicleListingDetail` in `api/schemas.py` — a `VehicleListing`
/// plus its description and every one of its photographs.
///
/// A separate type from `VehicleListing` rather than an extension of it,
/// because Dart has no cheap way to extend a class with `const` fields the
/// way the server extends its own Pydantic model — duplicating the shared
/// fields here is the honest cost of that, not an oversight.
library;

import 'listing_image.dart';

class VehicleListingDetail {
  const VehicleListingDetail({
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
    required this.description,
    required this.images,
  });

  final int id;
  final String? stockNumber;
  final String title;
  final String make;
  final String model;
  final int year;
  final String? variant;
  final String? price;
  final String status;
  final String processingStatus;
  final int imageCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  final String? description;
  final List<ListingImage> images;

  List<ListingImage> get originals =>
      images.where((i) => i.isOriginal).toList();

  List<ListingImage> get processed =>
      images.where((i) => i.isProcessed).toList();

  /// A shallow copy with [images] replaced — used after a delete, so the
  /// screen can drop one photograph from the list it already has rather than
  /// re-fetching the whole listing to lose one row.
  VehicleListingDetail copyWithImages(List<ListingImage> images) =>
      VehicleListingDetail(
        id: id,
        stockNumber: stockNumber,
        title: title,
        make: make,
        model: model,
        year: year,
        variant: variant,
        price: price,
        status: status,
        processingStatus: processingStatus,
        imageCount: imageCount,
        createdAt: createdAt,
        updatedAt: updatedAt,
        description: description,
        images: images,
      );

  factory VehicleListingDetail.fromJson(Map<String, dynamic> json) =>
      VehicleListingDetail(
        id: json['id'] as int,
        stockNumber: json['stock_number'] as String?,
        title: json['title'] as String,
        make: json['make'] as String,
        model: json['model'] as String,
        year: json['year'] as int,
        variant: json['variant'] as String?,
        price: json['price']?.toString(),
        status: json['status'] as String,
        processingStatus: json['processing_status'] as String,
        imageCount: json['image_count'] as int? ?? 0,
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
        description: json['description'] as String?,
        images: (json['images'] as List<dynamic>? ?? [])
            .map((e) => ListingImage.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
