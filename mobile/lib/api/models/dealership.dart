/// Mirrors `DealershipOut` in `api/schemas.py`.
///
/// The contact fields are only ever populated on the list a platform
/// administrator sees (`GET /api/platform/dealerships`) — the copy embedded
/// in `User.dealership` for an ordinary sign-in never needed them before now
/// and the server still sends them there too, so they are simply null for
/// every caller that has never used them rather than two different shapes
/// of the same schema.
library;

class Dealership {
  const Dealership({
    required this.id,
    required this.name,
    required this.location,
    required this.status,
    required this.userCount,
    this.contactName,
    this.contactEmail,
    this.contactPhone,
  });

  final int id;
  final String name;
  final String? location;
  final String status;
  final int userCount;
  final String? contactName;
  final String? contactEmail;
  final String? contactPhone;

  factory Dealership.fromJson(Map<String, dynamic> json) => Dealership(
    id: json['id'] as int,
    name: json['name'] as String,
    location: json['location'] as String?,
    status: json['status'] as String,
    userCount: json['user_count'] as int? ?? 0,
    contactName: json['contact_name'] as String?,
    contactEmail: json['contact_email'] as String?,
    contactPhone: json['contact_phone'] as String?,
  );
}
