/// A thin wrapper over `local_auth` — the only file that imports it, so this
/// app has one place that knows how to ask the device to authenticate rather
/// than that call scattered across every screen that might need it.
library;

import 'package:local_auth/local_auth.dart';

final _auth = LocalAuthentication();

/// Whether this device can authenticate at all — biometrics enrolled, or a
/// device passcode/PIN set. Checked before offering the Settings toggle in
/// the first place: turning on a lock the device can never satisfy would
/// trap someone out of their own signed-in session.
Future<bool> deviceSupportsAuthentication() async {
  try {
    return await _auth.isDeviceSupported();
  } catch (_) {
    return false;
  }
}

/// Prompts once. True on success; false on a cancel, a failure, or a
/// genuine platform error (biometrics newly disabled since the toggle was
/// turned on, a locked-out sensor, and so on) — every one of those is "not
/// unlocked" from the caller's side, and [AppLockScreen] offers "Try again"
/// regardless of which it was, so none needs distinguishing here.
///
/// `biometricOnly: false` lets the OS fall back to a device passcode when
/// biometrics fail or are not enrolled — the alternative would strand
/// someone whose face is not recognised in bad light with no way into their
/// own session. `persistAcrossBackgrounding: true` is local_auth 3.x's name
/// for what used to be called `stickyAuth` — the prompt survives a brief
/// backgrounding (a system alert stealing focus mid-check) instead of
/// failing outright.
Future<bool> authenticate() async {
  try {
    return await _auth.authenticate(
      localizedReason: 'Unlock AutoPivot',
      biometricOnly: false,
      persistAcrossBackgrounding: true,
    );
  } catch (_) {
    return false;
  }
}
