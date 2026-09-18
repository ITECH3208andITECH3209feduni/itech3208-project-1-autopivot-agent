/// Entry point for the dev tools build — screen previews with sample data,
/// and a way to sign in against any backend URL without rebuilding to change
/// it. See `dev/dev_tools_app.dart` for what it actually does.
///
///     flutter run -t lib/main_dev.dart
///     flutter build ios --debug --no-codesign --simulator -t lib/main_dev.dart
///
/// Never the target of a release build.
library;

import 'package:flutter/material.dart';

import 'dev/dev_tools_app.dart';

void main() => runApp(const DevToolsApp());
