/// Sample data and provider overrides for the dev tools screen.
///
/// Kept in one place rather than duplicated across each preview so a change
/// to a model's constructor only needs updating here — this is what
/// `main_preview_change_password.dart` and `main_preview_listings.dart`
/// originally hardcoded twice, before the dev tools screen unified them.
library;

import '../api/api_client.dart';
import '../api/models/dealership.dart';
import '../api/models/nav_counts.dart';
import '../api/models/user.dart';
import '../api/models/vehicle_listing.dart';
import '../auth/auth_controller.dart';

const sampleDealership = Dealership(
  id: 1,
  name: 'North Shore Motors',
  location: 'Auckland',
  status: 'active',
  userCount: 3,
);

User sampleUser({bool mustChangePassword = false}) => User(
  id: 1,
  email: 'demo@dealership.co.nz',
  firstName: 'Demo',
  lastName: 'Employee',
  role: 'staff',
  isActive: true,
  mustChangePassword: mustChangePassword,
  dealership: sampleDealership,
);

/// Holds [AuthState] fixed rather than restoring a real session.
///
/// Extends the real [AuthController] purely to satisfy [authProvider]'s
/// type — only [build] is overridden. Nothing here calls `restore`, and
/// nothing using this fixture should either: `restore` is inherited
/// unchanged from the real controller and would touch genuine secure storage
/// and a genuine network call if invoked, overwriting the very state this
/// class exists to hold still. That is also why a "preview" route built with
/// this fixture is never wrapped in `AppBootstrap` — that widget's only job
/// is to call `restore`, which is exactly what must not happen here.
class FixedAuthController extends AuthController {
  FixedAuthController(this._fixed);

  final AuthState _fixed;

  @override
  AuthState build() => _fixed;
}

/// A dealership's inventory, one vehicle per [ProcessingState] the listings
/// screen distinguishes, so every `StatusPill` colour can be seen at once.
List<VehicleListing> sampleListings() {
  final now = DateTime.now();
  return [
    VehicleListing(
      id: 1,
      stockNumber: 'ST-4471',
      title: '2021 Mazda CX-5 GT',
      make: 'Mazda',
      model: 'CX-5',
      year: 2021,
      variant: 'GT',
      price: null,
      status: 'active',
      processingStatus: 'complete',
      imageCount: 12,
      createdAt: now,
      updatedAt: now,
    ),
    VehicleListing(
      id: 2,
      stockNumber: 'ST-4472',
      title: '2015 Nissan Note DIG-S',
      make: 'Nissan',
      model: 'Note',
      year: 2015,
      variant: 'DIG-S',
      price: null,
      status: 'active',
      processingStatus: 'processing',
      imageCount: 20,
      createdAt: now,
      updatedAt: now,
    ),
    // No stock number, deliberately — exercises the row layout that omits
    // the "#... ·" separator rather than leaving it dangling.
    VehicleListing(
      id: 3,
      stockNumber: null,
      title: '2013 Mazda Premacy 20C Skyactiv',
      make: 'Mazda',
      model: 'Premacy',
      year: 2013,
      variant: '20C Skyactiv',
      price: null,
      status: 'draft',
      processingStatus: 'needs_review',
      imageCount: 7,
      createdAt: now,
      updatedAt: now,
    ),
    VehicleListing(
      id: 4,
      stockNumber: 'ST-4480',
      title: '2019 Toyota Corolla Hatch',
      make: 'Toyota',
      model: 'Corolla',
      year: 2019,
      variant: 'Hatch',
      price: null,
      status: 'active',
      processingStatus: 'pending',
      imageCount: 0,
      createdAt: now,
      updatedAt: now,
    ),
  ];
}

/// Returns [sampleListings] instead of making a network call.
class FakeApiClient extends ApiClient {
  @override
  Future<List<VehicleListing>> listings({
    int limit = 100,
    int offset = 0,
    String? query,
    String? processingStatus,
  }) async => sampleListings();

  @override
  Future<NavCounts> counts() async =>
      const NavCounts(vehicles: 4, backdrops: 2, needsReview: 1);
}
