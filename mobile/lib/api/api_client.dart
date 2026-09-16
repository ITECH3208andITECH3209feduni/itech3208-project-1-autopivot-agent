/// The one place that talks to the AutoPivot API.
///
/// Every request goes through here so the bearer header, the error mapping and
/// the base URL are decided once. Screens never see a `DioException`; they see
/// an [ApiException] whose message is already safe to put on screen.
library;

import 'dart:io' show Platform, SocketException;
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'api_exception.dart';
import 'models/backdrop.dart';
import 'models/dealership.dart';
import 'models/dealership_provisioned.dart';
import 'models/dealership_user.dart';
import 'models/listing_detail.dart';
import 'models/listing_image.dart';
import 'models/nav_counts.dart';
import 'models/processing_summary.dart';
import 'models/url_import_result.dart';
import 'models/url_vehicle_guess.dart';
import 'models/user.dart';
import 'models/vehicle_listing.dart';

/// What a successful sign-in returns.
class LoginResult {
  const LoginResult({
    required this.accessToken,
    required this.expiresIn,
    required this.user,
  });

  final String accessToken;

  /// Seconds. The server issues 8 hours (480 minutes) and there is no refresh
  /// token, so expiry means a clean return to sign-in rather than a silent
  /// renewal.
  final int expiresIn;

  final User user;
}

/// Where the API lives.
///
/// Overridable at build time so a physical device can reach a laptop on the
/// LAN without editing source:
///
///     flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000
///
/// The default is deliberately different on Android: an emulator cannot see
/// the host's `localhost`, which is its own loopback. `10.0.2.2` is the address
/// the Android emulator maps to the host machine, and getting this wrong looks
/// exactly like the server being down.
String defaultBaseUrl() {
  const fromEnv = String.fromEnvironment('API_BASE_URL');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (Platform.isAndroid) return 'http://10.0.2.2:8000';
  return 'http://localhost:8000';
}

class ApiClient {
  ApiClient({String? baseUrl})
    : _dio = Dio(
        BaseOptions(
          baseUrl: baseUrl ?? defaultBaseUrl(),
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30),
          // Every status is "successful" as far as dio is concerned; the
          // mapping below decides what each one means. Without this, dio
          // throws before the response body — which holds the server's own
          // message — can be read.
          validateStatus: (_) => true,
        ),
      );

  final Dio _dio;

  /// The bearer token, held in memory.
  ///
  /// Set by the auth controller after reading secure storage. Kept here rather
  /// than read from storage per request: storage is async, and a token lookup
  /// on every image tile would be a lot of Keychain round trips.
  String? _token;

  set token(String? value) => _token = value;

  String get baseUrl => _dio.options.baseUrl;

  String? get _bearer => _token == null ? null : 'Bearer $_token';

  /// The entry is omitted entirely when there is no token, rather than sent
  /// empty — an `Authorization:` header with no value is a malformed request,
  /// not an anonymous one.
  Map<String, String> get _headers => {'Authorization': ?_bearer};

  // ── Auth ────────────────────────────────────────────────────────────────

  Future<LoginResult> login({
    required String email,
    required String password,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/auth/login',
        data: {'email': email, 'password': password},
      ),
      // The sign-in endpoint returns an identical 401 for unknown email, wrong
      // password and deactivated account, so that it cannot be used to discover
      // which addresses have accounts. One message for all three.
      onUnauthorised: () => const ApiInvalidCredentialsException(),
    );

    return LoginResult(
      accessToken: json['access_token'] as String,
      expiresIn: json['expires_in'] as int? ?? 0,
      user: User.fromJson(json['user'] as Map<String, dynamic>),
    );
  }

  /// The signed-in user, re-read from the server.
  ///
  /// Called on start-up to validate a stored token rather than trusting it.
  /// `is_active` is checked server-side on every request, so an account
  /// deactivated since the token was issued stops working immediately.
  Future<User> me() async {
    final json = await _send(() => _dio.get('/auth/me', options: _options()));
    return User.fromJson(json);
  }

  Future<User> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/auth/change-password',
        data: {
          'current_password': currentPassword,
          'new_password': newPassword,
        },
        options: _options(),
      ),
    );
    return User.fromJson(json);
  }

  // ── Listings ────────────────────────────────────────────────────────────

  /// The dealership's vehicles.
  ///
  /// [limit] is passed explicitly because the server defaults to 20. Leaving it
  /// unset makes a dealership with fifty vehicles look like it has twenty, with
  /// nothing on screen to say otherwise.
  Future<List<VehicleListing>> listings({
    int limit = 100,
    int offset = 0,
    String? query,
    String? processingStatus,
  }) async {
    final json = await _sendList(
      () => _dio.get(
        '/api/listings',
        queryParameters: {
          'limit': limit,
          'offset': offset,
          if (query != null && query.isNotEmpty) 'q': query,
          'processing_status': ?processingStatus,
        },
        options: _options(),
      ),
    );
    return json
        .map((e) => VehicleListing.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// One vehicle, with its description and every photograph attached to it.
  Future<VehicleListingDetail> listing(int listingId) async {
    final json = await _send(
      () => _dio.get('/api/listings/$listingId', options: _options()),
    );
    return VehicleListingDetail.fromJson(json);
  }

  /// Creates a new listing. `make`, `model` and `year` are the server's own
  /// minimum — they are `NOT NULL` columns, so a listing genuinely cannot
  /// exist from photographs alone, which is why the capture screen asks for
  /// them at submit time rather than assuming a details step happens
  /// elsewhere.
  Future<VehicleListingDetail> createListing({
    required String make,
    required String model,
    required int year,
    String? variant,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/api/listings',
        data: {'make': make, 'model': model, 'year': year, 'variant': ?variant},
        options: _options(),
      ),
    );
    return VehicleListingDetail.fromJson(json);
  }

  /// Attaches original photographs to a listing. [filePaths] become one
  /// multipart file each, all under the field name the server's
  /// `files: list[UploadFile]` expects — a single list value in dio's
  /// [FormData] produces exactly that repeated-field shape.
  Future<List<ListingImage>> uploadImages(
    int listingId,
    List<String> filePaths,
  ) async {
    final formData = FormData();
    for (final path in filePaths) {
      formData.files.add(MapEntry('files', await MultipartFile.fromFile(path)));
    }
    final json = await _sendList(
      () => _dio.post(
        '/api/listings/$listingId/images',
        data: formData,
        options: _options(),
      ),
    );
    return json
        .map((e) => ListingImage.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Removes one photograph. The server enforces what may not be deleted —
  /// an image another job still depends on comes back as
  /// [ApiRequestException] with status 409, which already carries a message
  /// safe to show as-is; this method does not special-case it.
  Future<void> deleteImage(int listingId, int imageId) async {
    await _guardVoid(
      () => _dio.delete(
        '/api/listings/$listingId/images/$imageId',
        options: _options(),
      ),
    );
  }

  /// Guesses year/make/model/variant from a listing URL's own slug — see
  /// `UrlVehicleGuess`'s own doc comment. Never fetches the far page itself,
  /// so this is cheap enough to call as soon as a dealer pastes a URL, before
  /// any listing exists to attach it to.
  Future<UrlVehicleGuess> parseListingUrl(String url) async {
    final json = await _send(
      () => _dio.post(
        '/api/listings/parse-url',
        data: {'url': url},
        options: _options(),
      ),
    );
    return UrlVehicleGuess.fromJson(json);
  }

  /// Imports photographs found on a listing page directly onto [listingId].
  /// Not every site can be read this way — see `api/url_import.py`'s own
  /// doc comment for the two known failure shapes — and a refusal surfaces
  /// as an ordinary [ApiRequestException] whose message names the reason.
  Future<UrlImportResult> importImagesFromUrl(int listingId, String url) async {
    final json = await _send(
      () => _dio.post(
        '/api/listings/$listingId/images/from-url',
        data: {'url': url},
        options: _options(),
      ),
    );
    return UrlImportResult.fromJson(json);
  }

  /// Overrides the classifier's exclusion for one original photograph — see
  /// the server route's own doc comment for why this is a one-way door
  /// rather than a toggle.
  Future<ListingImage> includeImage(int listingId, int imageId) async {
    final json = await _send(
      () => _dio.post(
        '/api/listings/$listingId/images/$imageId/include',
        options: _options(),
      ),
    );
    return ListingImage.fromJson(json);
  }

  /// The dealership's backdrop library, to offer as a choice before queueing
  /// a listing for processing. Empty for a dealership that has not added one
  /// yet — there is no shipped default set (see `routes_backdrops.py`).
  Future<List<Backdrop>> backdrops() async {
    final json = await _sendList(
      () => _dio.get('/api/backdrops', options: _options()),
    );
    return json
        .map((e) => Backdrop.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Queues every unprocessed photograph on a listing. [backdropId] is
  /// optional — without one the vehicle comes back on a transparent
  /// background, per `ProcessRequest`'s own doc comment.
  Future<ProcessingSummary> processListing(
    int listingId, {
    int? backdropId,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/api/listings/$listingId/process',
        data: {'backdrop_id': ?backdropId},
        options: _options(),
      ),
    );
    return ProcessingSummary.fromJson(json);
  }

  /// Progress for a listing already queued — what a polling results screen
  /// asks for. See `ProcessingSummary.isInProgress` for when to stop.
  Future<ProcessingSummary> listingJobs(int listingId) async {
    final json = await _send(
      () => _dio.get('/api/listings/$listingId/jobs', options: _options()),
    );
    return ProcessingSummary.fromJson(json);
  }

  Future<NavCounts> counts() async {
    final json = await _send(
      () => _dio.get('/api/dashboard/counts', options: _options()),
    );
    return NavCounts.fromJson(json);
  }

  // ── Dealership team ─────────────────────────────────────────────────────
  //
  // All four endpoints are `require_roles("dealership_admin")` server-side —
  // see `api/routes_dealership_users.py` — so a non-admin calling any of
  // these gets a 403 `ApiRequestException` regardless of what the client
  // shows. The screens that call these still gate the entry point on
  // `User.role` themselves, since asking the server "no" is a worse first
  // experience than never offering the button.

  /// Every user in the caller's own dealership — an admin can only ever see
  /// and manage their own, which the server enforces independently of this
  /// client ever asking for anyone else's.
  Future<List<DealershipUser>> dealershipUsers() async {
    final json = await _sendList(
      () => _dio.get('/api/dealership/users', options: _options()),
    );
    return json
        .map((e) => DealershipUser.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Provisions a new team member with a server-generated password — see
  /// [DealershipUserProvisioned.initialPassword]'s own doc comment for why
  /// that value only ever appears in this one response.
  Future<DealershipUserProvisioned> addDealershipUser({
    required String email,
    required String firstName,
    required String lastName,
    required String role,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/api/dealership/users',
        data: {
          'email': email,
          'first_name': firstName,
          'last_name': lastName,
          'role': role,
        },
        options: _options(),
      ),
    );
    return DealershipUserProvisioned.fromJson(json);
  }

  /// Rotates a team member's password to a new server-generated one and
  /// returns it — same one-time-only shape as [addDealershipUser]. The
  /// server rejects this for an already-deactivated account (409), which
  /// surfaces as an ordinary [ApiRequestException].
  Future<String> resetDealershipUserPassword(int userId) async {
    final json = await _send(
      () => _dio.post(
        '/api/dealership/users/$userId/reset-password',
        options: _options(),
      ),
    );
    return json['initial_password'] as String;
  }

  /// Deactivates a team member. There is deliberately no matching
  /// "reactivate" — the server has no such endpoint (see
  /// `routes_dealership_users.py`), so this client does not offer one
  /// either rather than pointing at a 404.
  Future<DealershipUser> deactivateDealershipUser(int userId) async {
    final json = await _send(
      () => _dio.post(
        '/api/dealership/users/$userId/deactivate',
        options: _options(),
      ),
    );
    return DealershipUser.fromJson(json);
  }

  // ── Platform administration ─────────────────────────────────────────────
  //
  // Both endpoints are `require_roles("platform_admin")` server-side — see
  // `api/routes_platform_admin.py` — the same belt-and-suspenders relationship
  // to the client-side role gate as the dealership-team endpoints above.

  /// Every dealership on the platform, not just the caller's own — a
  /// platform administrator belongs to none (see `User.dealership`'s own
  /// doc comment) and manages all of them.
  Future<List<Dealership>> platformDealerships() async {
    final json = await _sendList(
      () => _dio.get('/api/platform/dealerships', options: _options()),
    );
    return json
        .map((e) => Dealership.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Creates a dealership and its first administrator account together —
  /// the server refuses to create one without the other (see
  /// `onboard_dealership` in `routes_platform_admin.py`), so there is no
  /// separate "create the dealership, then add its first user" pair of
  /// calls to sequence here.
  Future<DealershipProvisioned> onboardDealership({
    required String name,
    required String location,
    required String contactName,
    required String contactEmail,
    required String contactPhone,
    required String adminEmail,
    required String adminFirstName,
    required String adminLastName,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/api/platform/dealerships',
        data: {
          'name': name,
          'location': location,
          'contact_name': contactName,
          'contact_email': contactEmail,
          'contact_phone': contactPhone,
          'admin_email': adminEmail,
          'admin_first_name': adminFirstName,
          'admin_last_name': adminLastName,
        },
        options: _options(),
      ),
    );
    return DealershipProvisioned.fromJson(json);
  }

  // The platform-administrator equivalents of the four dealership-team
  // methods above — same shapes, scoped by an explicit dealership id rather
  // than the caller's own, since a platform administrator belongs to none.
  // See api/routes_platform_dealership_users.py's own doc comment for why
  // this is a separate route family rather than the existing one accepting
  // a second actor.

  Future<List<DealershipUser>> platformDealershipUsers(int dealershipId) async {
    final json = await _sendList(
      () => _dio.get(
        '/api/platform/dealerships/$dealershipId/users',
        options: _options(),
      ),
    );
    return json
        .map((e) => DealershipUser.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<DealershipUserProvisioned> addPlatformDealershipUser(
    int dealershipId, {
    required String email,
    required String firstName,
    required String lastName,
    required String role,
  }) async {
    final json = await _send(
      () => _dio.post(
        '/api/platform/dealerships/$dealershipId/users',
        data: {
          'email': email,
          'first_name': firstName,
          'last_name': lastName,
          'role': role,
        },
        options: _options(),
      ),
    );
    return DealershipUserProvisioned.fromJson(json);
  }

  Future<String> resetPlatformDealershipUserPassword(
    int dealershipId,
    int userId,
  ) async {
    final json = await _send(
      () => _dio.post(
        '/api/platform/dealerships/$dealershipId/users/$userId/reset-password',
        options: _options(),
      ),
    );
    return json['initial_password'] as String;
  }

  Future<DealershipUser> deactivatePlatformDealershipUser(
    int dealershipId,
    int userId,
  ) async {
    final json = await _send(
      () => _dio.post(
        '/api/platform/dealerships/$dealershipId/users/$userId/deactivate',
        options: _options(),
      ),
    );
    return DealershipUser.fromJson(json);
  }

  // ── Files ───────────────────────────────────────────────────────────────

  /// Raw bytes for a stored image.
  ///
  /// `/api/files/{path}` requires the bearer header, which is why an ordinary
  /// `Image.network` gets a 401 — Flutter does not attach it. Everything that
  /// displays a stored image goes through here.
  Future<Uint8List> fileBytes(String storagePath) async {
    final path = storagePath.startsWith('/api/files/')
        ? storagePath
        : '/api/files/$storagePath';

    late Response<dynamic> response;
    try {
      response = await _dio.get(
        path,
        options: Options(headers: _headers, responseType: ResponseType.bytes),
      );
    } on DioException catch (e) {
      throw _fromDio(e);
    }

    _throwForStatus(response, null);
    return Uint8List.fromList(response.data as List<int>);
  }

  // ── Plumbing ────────────────────────────────────────────────────────────

  Options _options() => Options(headers: _headers);

  Future<Map<String, dynamic>> _send(
    Future<Response<dynamic>> Function() request, {
    ApiException Function()? onUnauthorised,
  }) async {
    final response = await _guard(request);
    _throwForStatus(response, onUnauthorised);

    final data = response.data;
    if (data is Map<String, dynamic>) return data;
    throw const ApiServerException();
  }

  Future<List<dynamic>> _sendList(
    Future<Response<dynamic>> Function() request,
  ) async {
    final response = await _guard(request);
    _throwForStatus(response, null);

    final data = response.data;
    if (data is List) return data;
    throw const ApiServerException();
  }

  /// For a 204 with no body — deletion, mainly. `_send`/`_sendList` both
  /// throw on exactly this response shape, since a missing body is normally
  /// a sign something went wrong; here it is the success case.
  Future<void> _guardVoid(Future<Response<dynamic>> Function() request) async {
    final response = await _guard(request);
    _throwForStatus(response, null);
  }

  Future<Response<dynamic>> _guard(
    Future<Response<dynamic>> Function() request,
  ) async {
    try {
      return await request();
    } on DioException catch (e) {
      throw _fromDio(e);
    }
  }

  void _throwForStatus(
    Response<dynamic> response,
    ApiException Function()? onUnauthorised,
  ) {
    final status = response.statusCode ?? 0;
    if (status >= 200 && status < 300) return;

    if (status == 401) {
      throw onUnauthorised?.call() ?? const ApiUnauthorisedException();
    }
    if (status >= 500) throw const ApiServerException();

    throw ApiRequestException(_detail(response.data), statusCode: status);
  }

  /// FastAPI's `detail`, which is a string for errors we raise and a list of
  /// objects for a 422 from validation. Neither is safe to render blindly.
  String _detail(dynamic data) {
    if (data is Map<String, dynamic>) {
      final detail = data['detail'];
      if (detail is String && detail.isNotEmpty) return detail;
      if (detail is List) {
        final messages = detail
            .whereType<Map>()
            .map((e) => e['msg'])
            .whereType<String>()
            .toList();
        if (messages.isNotEmpty) return messages.join('. ');
      }
    }
    return 'That request could not be completed.';
  }

  /// Transport failures become [ApiNetworkException] and nothing else.
  ///
  /// This is the line that keeps a backend restart from signing the user out:
  /// only a real 401 produces an unauthorised error, and only an unauthorised
  /// error clears the token.
  ApiException _fromDio(DioException e) {
    if (e.error is SocketException) return const ApiNetworkException();

    return switch (e.type) {
      DioExceptionType.connectionTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.receiveTimeout => const ApiNetworkException(
        'AutoPivot took too long to respond. Please try again.',
      ),
      DioExceptionType.connectionError ||
      DioExceptionType.unknown => const ApiNetworkException(),
      DioExceptionType.cancel => const ApiNetworkException(
        'That request was cancelled.',
      ),
      DioExceptionType.badCertificate => const ApiNetworkException(
        'The connection to AutoPivot could not be trusted.',
      ),
      DioExceptionType.badResponse => const ApiServerException(),
      // A wildcard rather than an exhaustive list: dio adds enum members
      // between minor versions, and a new transport failure should degrade to
      // "could not reach the server" rather than stop the app compiling.
      _ => const ApiNetworkException(),
    };
  }
}
