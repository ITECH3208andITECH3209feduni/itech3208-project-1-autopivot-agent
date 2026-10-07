/// Saves an in-progress capture set so it survives the app being closed —
/// the "Save Draft" option on the exit-confirmation dialog in
/// [CaptureScreen].
///
/// The `camera` plugin writes each shot to the OS temporary directory, which
/// iOS is free to clear at any time — nothing about a "temporary" file is
/// guaranteed to still exist the next time the app launches. A draft copies
/// every captured file into the app's own documents directory instead, which
/// persists until the app deletes it, and writes a small JSON manifest
/// alongside them recording which [CaptureAngle] each file belongs to,
/// which angles were deliberately skipped, and any submit of the set that
/// created its listing and stopped short ([UnfinishedSubmission]), so that
/// retrying the resumed set carries on with that listing.
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
import 'capture_submission.dart';

class CaptureDraft {
  const CaptureDraft({
    required this.files,
    required this.skipped,
    required this.savedAt,
    this.unfinishedSubmission,
  });

  /// Angle to the copied file holding that shot, in the draft directory.
  final Map<CaptureAngle, File> files;
  final Set<CaptureAngle> skipped;
  final DateTime savedAt;

  /// A submit of this set that created its listing and stopped short, for
  /// [CaptureSubmission.resume]. Null when there was none, and for every
  /// draft saved before these were kept.
  final UnfinishedSubmission? unfinishedSubmission;

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

// Draft operations run one at a time, in the order they were asked for. The
// capture screen saves after every shot without waiting for the save to
// finish, so one save can still be copying when the next shot's save — or a
// discard — begins, and run together each would delete the directory the
// other is still working in.
Future<void> _pending = Future<void>.value();

Future<T> _serialised<T>(Future<T> Function() operation) {
  final result = _pending.then((_) => operation());
  // A failed operation must not stall every one queued behind it.
  _pending = result.then<void>((_) {}, onError: (Object _) {});
  return result;
}

/// Copies every captured photograph into the draft directory and writes the
/// manifest. Safe to call over an existing draft — the new set replaces the
/// old one whole, so a draft never mixes files from two different saves.
/// [unfinishedSubmission] is kept with it, and replaced as whole: every save
/// passes whatever is unfinished at the time, or nothing.
Future<void> saveCaptureDraft({
  required Map<CaptureAngle, String> capturedPaths,
  required Set<CaptureAngle> skipped,
  UnfinishedSubmission? unfinishedSubmission,
}) => _serialised(
  () => _saveDraft(capturedPaths, skipped, unfinishedSubmission),
);

Future<void> _saveDraft(
  Map<CaptureAngle, String> capturedPaths,
  Set<CaptureAngle> skipped,
  UnfinishedSubmission? unfinishedSubmission,
) async {
  final dir = await _draftDir();
  // Built beside the live draft and swapped in only once complete. Clearing
  // the draft directory first — what this used to do — deleted the very files
  // a resumed draft's photographs point at, so the first save after a resume
  // destroyed the resumed shots and then failed copying from paths it had
  // just removed.
  final staging = Directory('${dir.path}.saving');
  if (await staging.exists()) await staging.delete(recursive: true);
  await staging.create(recursive: true);

  final entries = <String, String>{};
  final names = <String>{};
  for (final MapEntry(key: angle, value: sourcePath) in capturedPaths.entries) {
    // Each copy keeps its photograph's own file name, the one the camera gave
    // it, because that is the name an upload is filed under on the server,
    // and a submit that stopped short knows what it already sent by it (see
    // UnfinishedSubmission). Copies named after their angles, as they used
    // to be, looked after a resume like photographs the server had never
    // seen, and sending them again was refused as duplicates. The camera
    // names every shot apart, so the angle is added only in case two
    // photographs of one set ever arrive under the same name, rather than
    // letting one copy overwrite the other.
    var name = sourcePath.substring(sourcePath.lastIndexOf('/') + 1);
    if (!names.add(name)) {
      name = '${angle.name}-$name';
      names.add(name);
    }
    await File(sourcePath).copy('${staging.path}/$name');
    // Recorded where the file will be once the staging directory takes the
    // draft's place. A resumed photograph is copied under the name it already
    // has, so its path stays valid across the swap.
    entries[angle.name] = '${dir.path}/$name';
  }

  final manifest = {
    'saved_at': DateTime.now().toIso8601String(),
    'files': entries,
    'skipped': skipped.map((a) => a.name).toList(),
    // Left out when there is none, as it is from every draft saved before
    // these were kept, which is how those still load: as having none.
    if (unfinishedSubmission != null)
      'unfinished_submission': unfinishedSubmission.toJson(),
  };
  await File('${staging.path}/manifest.json').writeAsString(jsonEncode(manifest));

  await dir.delete(recursive: true);
  await staging.rename(dir.path);
}

/// Reads back a saved draft, or null if there is none — the ordinary case,
/// since most capture sessions end in a submit, not a save.
Future<CaptureDraft?> loadCaptureDraft() => _serialised(_loadDraft);

Future<CaptureDraft?> _loadDraft() async {
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
      // Null, never a throw, for one that is missing or unreadable: the
      // photographs above are worth resuming either way.
      unfinishedSubmission: UnfinishedSubmission.fromJson(
        json['unfinished_submission'],
      ),
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
Future<void> clearCaptureDraft() => _serialised(() async {
  final dir = await _draftDir();
  if (await dir.exists()) await dir.delete(recursive: true);
});
