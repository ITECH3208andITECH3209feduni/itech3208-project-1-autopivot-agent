/// Mirrors `UrlVehicleGuess` in `api/schemas.py` — what
/// `url_import.guess_vehicle_from_url` read out of a pasted listing URL's own
/// slug. Every field is nullable: a URL that does not match a known shape
/// comes back with all four null, not a wrong guess.
library;

class UrlVehicleGuess {
  const UrlVehicleGuess({this.year, this.make, this.model, this.variant});

  final int? year;
  final String? make;
  final String? model;
  final String? variant;

  bool get isEmpty => year == null && make == null && model == null;

  factory UrlVehicleGuess.fromJson(Map<String, dynamic> json) =>
      UrlVehicleGuess(
        year: json['year'] as int?,
        make: json['make'] as String?,
        model: json['model'] as String?,
        variant: json['variant'] as String?,
      );
}
