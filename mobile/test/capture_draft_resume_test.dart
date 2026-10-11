// The "Resume your last capture?" prompt:
// lib/features/capture/draft_resume_prompt.dart.
//
// Answering Discard deletes every photograph the saved draft holds, so
// nothing but a tap on Discard may come back as that answer. Android's system
// Back is sent the way the platform sends it, as a popRoute message on the
// navigation channel (the same helper Flutter's own navigator tests use),
// rather than by popping the dialog route directly. Popping it directly is the
// other case: the route removed by something other than the photographer.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/draft_resume_prompt.dart';

const _title = 'Resume your last capture?';

/// What Android's embedding sends when the system Back button is pressed.
Future<void> _pressAndroidBack() => TestDefaultBinaryMessengerBinding
    .instance
    .defaultBinaryMessenger
    .handlePlatformMessage(
      SystemChannels.navigation.name,
      const JSONMessageCodec().encodeMessage(<String, dynamic>{
        'method': 'popRoute',
      }),
      (_) {},
    );

void main() {
  /// Puts the prompt up over an otherwise empty app. The getter it returns
  /// reads the prompt's answer, which stays null for as long as it is
  /// unanswered.
  Future<bool? Function()> showPrompt(WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    bool? answer;
    unawaited(
      askToResumeDraft(
        tester.element(find.byType(SizedBox)),
        shotCount: 3,
      ).then((value) => answer = value),
    );
    await tester.pumpAndSettle();
    expect(find.text(_title), findsOneWidget);
    return () => answer;
  }

  testWidgets('Android Back leaves the prompt up rather than discarding', (
    tester,
  ) async {
    final answer = await showPrompt(tester);

    await _pressAndroidBack();
    await tester.pumpAndSettle();

    expect(find.text(_title), findsOneWidget);
    expect(answer(), isNull);
  });

  testWidgets('a prompt closed without an answer keeps the draft', (
    tester,
  ) async {
    final answer = await showPrompt(tester);

    Navigator.of(tester.element(find.byType(AlertDialog))).pop();
    await tester.pumpAndSettle();

    expect(answer(), isTrue);
  });

  testWidgets('Discard is the one answer that gives the draft up', (
    tester,
  ) async {
    final answer = await showPrompt(tester);

    await tester.tap(find.text('Discard'));
    await tester.pumpAndSettle();

    expect(answer(), isFalse);
  });

  testWidgets('Resume picks the draft back up', (tester) async {
    final answer = await showPrompt(tester);

    await tester.tap(find.text('Resume'));
    await tester.pumpAndSettle();

    expect(answer(), isTrue);
  });
}
