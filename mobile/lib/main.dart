/// Entry point.
///
/// The whole app lives under one [ProviderScope] so [authProvider] is a
/// single instance shared by the router's redirect logic, the splash and
/// unavailable screens in [AutoPivotApp], and every feature screen — there is
/// exactly one source of truth for the session, never one per screen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'bootstrap.dart';

void main() {
  runApp(
    const ProviderScope(
      child: AppBootstrap(child: AutoPivotApp()),
    ),
  );
}
