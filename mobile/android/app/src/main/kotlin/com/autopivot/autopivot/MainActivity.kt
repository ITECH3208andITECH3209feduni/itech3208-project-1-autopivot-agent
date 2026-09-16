package com.autopivot.autopivot

import io.flutter.embedding.android.FlutterFragmentActivity

// FlutterFragmentActivity, not FlutterActivity: local_auth's Android side
// shows a biometric prompt through AndroidX's Fragment-based BiometricPrompt
// API, which needs a FragmentActivity host. FlutterActivity is not one —
// biometric unlock fails at runtime without this change, not at compile time.
class MainActivity : FlutterFragmentActivity()
