/// Mirrors `DealershipOut` in `api/schemas.py`.
library;

class Dealership {
  const Dealership({
    required this.id,
    required this.name,
    required this.location,
    required this.status,
    required this.userCount,
  });

  final int id;
  final String name;
  final String? location;
  final String status;
  final int userCount;

  factory Dealership.fromJson(Map<String, dynamic> json) => Dealership(
    id: json['id'] as int,
    name: json['name'] as String,
    location: json['location'] as String?,
    status: json['status'] as String,
    userCount: json['user_count'] as int? ?? 0,
  );
}
