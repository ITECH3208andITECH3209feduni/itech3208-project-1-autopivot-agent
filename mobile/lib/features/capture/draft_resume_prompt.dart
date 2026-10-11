/// The "Resume your last capture?" prompt [CaptureScreen] shows when it
/// opens over a saved draft (see `capture_draft.dart` for what a draft is).
///
/// Its own file so the prompt can be tested without the camera screen around
/// it, whose camera, motion sensors and on-device vehicle check all need
/// hardware a widget test does not have.
library;

import 'package:flutter/material.dart';

import 'capture_angles.dart';

/// Asks whether to pick a saved draft of [shotCount] photographs back up.
///
/// False only for an explicit tap on Discard, the one answer that deletes
/// the draft. The dialog ignores Android's system Back, and if its route is
/// removed some other way the answer is resume: a draft kept by mistake can
/// still be discarded, a draft deleted by mistake can never be brought back.
Future<bool> askToResumeDraft(
  BuildContext context, {
  required int shotCount,
}) async {
  final resume = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) => PopScope(
      // barrierDismissible above only covers a tap outside the dialog.
      // Android's system Back pops it regardless, and that pop came back as
      // no answer at all, which is how Back used to delete every photograph
      // in the draft without asking.
      canPop: false,
      child: AlertDialog(
        title: const Text('Resume your last capture?'),
        content: Text(
          '$shotCount of ${CaptureAngle.values.length} photographs '
          'were saved before you left the camera.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Discard'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Resume'),
          ),
        ],
      ),
    ),
  );
  return resume != false;
}
