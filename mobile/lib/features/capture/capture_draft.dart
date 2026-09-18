/// Saves an in-progress capture set so it survives the app being closed —
/// the "Save Draft" option on the exit-confirmation dialog in
/// [CaptureScreen].
///
/// The `camera` plugin writes each shot to the OS temporary directory, which
/// iOS is free to clear at any time — nothing about a "temporary" file is
/// guaranteed to still exist the next time the app launches. A draft copies
/// every captured file into the app's own documents directory instead, which
/// persists until the app deletes it, and writes a small JSON manifest
/// alongside them recording which [CaptureAngle] each file belongs to and
/// which angles were deliberately skipped.
///
/// Deliberately one draft, not several: a photographer walks around one
/// vehicle at a time, and a list of abandoned drafts to manage would be a
/// second thing to keep track of for a workflow this app is trying to make
/// faster, not slower. Starting a new capture after saving a draft, without
/// resuming it first, silently overwrites it — the same trade-off a single
/// working document makes.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'capture_angles.dart';

class CaptureDraft {
  const CaptureDraft({
    required this.files,
    required this.skipped,
    required this.savedAt,
  });

  /// Angle to the copied file holding that shot, in the draft directory.
  final Map<CaptureAngle, File> files;
  final Set<CaptureAngle> skipped;
  final DateTime savedAt;

  int get shotCount => files.length;
}

Future<Directory> _draftDir() async {
  final docs = await getApplicationDocumentsDirectory();
  final dir = Directory('${docs.path}/capture_draft');
  if (!await dir.exists()) await dir.create(recursive: true);
  return dir;
}

Future<File> _manifestFile() async {
  final dir = await _draftDir();
  return File('${dir.path}/manifest.json');
}

/// Copies every captured photograph into the draft directory and writes the
/// manifest. Safe to call over an existing draft — the directory is cleared
/// first, so a draft never mixes files from two different saves.
Future<void> saveCaptureDraft({
  required Map<CaptureAngle, String> capturedPaths,
  required Set<CaptureAngle> skipped,
}) async {
  final dir = await _draftDir();
  // Clear anything left from a previous draft before copying the new set in,
  // so a stale file from an earlier save can never be mistaken for part of
  // this one.
  if (await dir.exists()) await dir.delete(recursive: true);
  await dir.create(recursive: true);

  final entries = <String, String>{};
  for (final MapEntry(key: angle, value: sourcePath) in capturedPaths.entries) {
    final ext = sourcePath.contains('.') ? sourcePath.split('.').last : 'jpg';
    final destPath = '${dir.path}/${angle.name}.$ext';
    await File(sourcePath).copy(destPath);
    entries[angle.name] = destPath;
  }

  final manifest = {
    'saved_at': DateTime.now().toIso8601String(),
    'files': entries,
    'skipped': skipped.map((a) => a.name).toList(),
  };
  await (await _manifestFile()).writeAsString(jsonEncode(manifest));
}

/// Reads back a saved draft, or null if there is none — the ordinary case,
/// since most capture sessions end in a submit, not a save.
Future<CaptureDraft?> loadCaptureDraft() async {
  final manifest = await _manifestFile();
  if (!await manifest.exists()) return null;

  try {
    final byName = {for (final a in CaptureAngle.values) a.name: a};
    final json =
        jsonDecode(await manifest.readAsString()) as Map<String, dynamic>;
    final rawFiles = (json['files'] as Map<String, dynamic>? ?? {});
    final files = <CaptureAngle, File>{};
    for (final MapEntry(key: name, value: path) in rawFiles.entries) {
      final angle = byName[name];
      final file = File(path as String);
      if (angle != null && await file.exists()) files[angle] = file;
    }
    final skipped = (json['skipped'] as List<dynamic>? ?? [])
        .map((name) => byName[name])
        .whereType<CaptureAngle>()
        .toSet();
    if (files.isEmpty && skipped.isEmpty) return null;

    return CaptureDraft(
      files: files,
      skipped: skipped,
      savedAt:
          DateTime.tryParse(json['saved_at'] as String? ?? '') ??
          DateTime.now(),
    );
  } catch (_) {
    // A manifest that fails to parse is not a draft worth resuming — treated
    // as though none exists rather than surfacing a crash over a feature
    // whose whole point is not losing work.
    return null;
  }
}

/// Discards a saved draft — called once its photographs are safely uploaded,
/// or when the photographer chooses to discard it outright.
Future<void> clearCaptureDraft() async {
  final dir = await _draftDir();
  if (await dir.exists()) await dir.delete(recursive: true);
}
