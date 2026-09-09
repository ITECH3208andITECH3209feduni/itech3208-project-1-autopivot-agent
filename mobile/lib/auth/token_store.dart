/// Where the session token lives.
///
/// Platform secure storage, not shared preferences: the Keychain on iOS, and
/// on Android AES-GCM data encryption with the key wrapped by RSA in the
/// hardware keystore. A bearer token in plain preferences is readable by
/// anything with filesystem access on a rooted or jailbroken device, and this
/// one is good for eight hours against a dealership's whole inventory.
///
/// The brief specifies EncryptedSharedPreferences, which is what
/// flutter_secure_storage used before version 10. Version 11 replaced it with
/// the keystore-backed scheme above, so the default is now stronger than the
/// brief asked for and there is nothing to configure.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStore {
  const TokenStore(this._storage);

  static const _key = 'autopivot.access_token';

  final FlutterSecureStorage _storage;

  /// Sensible defaults for both platforms.
  ///
  /// `first_unlock` rather than the stricter `passcode` option: an employee
  /// photographing a lot should not be signed out because the phone locked in
  /// their pocket, and the token expires in eight hours regardless.
  factory TokenStore.standard() => const TokenStore(
    FlutterSecureStorage(
      // Defaults are correct here: AES-GCM storage, RSA-wrapped key, and
      // resetOnError so a corrupt entry clears itself rather than bricking
      // sign-in.
      aOptions: AndroidOptions(),
      iOptions: IOSOptions(
        accessibility: KeychainAccessibility.first_unlock,
      ),
    ),
  );

  Future<String?> read() async {
    try {
      return await _storage.read(key: _key);
    } catch (_) {
      // A corrupt or unreadable keychain entry must not stop the app from
      // starting. Treated as "no token", which sends the user to sign in.
      return null;
    }
  }

  Future<void> write(String token) => _storage.write(key: _key, value: token);

  Future<void> clear() => _storage.delete(key: _key);
}
