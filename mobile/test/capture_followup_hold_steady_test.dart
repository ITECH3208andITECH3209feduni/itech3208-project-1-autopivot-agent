// The shutter's last gate: lib/features/capture/hold_steady.dart.
//
// Every on-device check has to have agreed for the whole window, about the shot
// actually being taken, before the shutter enables. The time is handed in
// rather than read from a clock, so each case states exactly how long has
// passed.
//
// Plain test(): nothing here draws a widget.

import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/features/capture/capture_angles.dart';
import 'package:autopivot/features/capture/hold_steady.dart';

const _window = Duration(milliseconds: 600);

final _start = DateTime(2026, 9, 25, 9);

/// [ms] milliseconds into the test.
DateTime _at(int ms) => _start.add(Duration(milliseconds: ms));

void main() {
  test('a shot settles once the checks have agreed for the whole window', () {
    final gate = HoldSteady(_window)
      ..update(target: CaptureAngle.front, ready: true, now: _at(0));

    expect(gate.isSettled(target: CaptureAngle.front, now: _at(599)), isFalse);
    expect(gate.isSettled(target: CaptureAngle.front, now: _at(600)), isTrue);
  });

  test('a check that blocks part-way through starts the window over', () {
    final gate = HoldSteady(_window)
      ..update(target: CaptureAngle.front, ready: true, now: _at(0))
      ..update(target: CaptureAngle.front, ready: false, now: _at(300))
      ..update(target: CaptureAngle.front, ready: true, now: _at(400));

    expect(gate.isSettled(target: CaptureAngle.front, now: _at(999)), isFalse);
    expect(gate.isSettled(target: CaptureAngle.front, now: _at(1000)), isTrue);
  });

  test('the next angle has to be held for itself, even with every check '
      'still agreeing from the spot the last one was shot from', () {
    // Right side and rear-right corner want different tilts, but their ±4°
    // windows overlap, and the vehicle check only asks whether a car is in
    // frame, so nothing blocks a second shot from exactly the same spot.
    final gate = HoldSteady(_window)
      ..update(target: CaptureAngle.rightSide, ready: true, now: _at(0));
    expect(
      gate.isSettled(target: CaptureAngle.rightSide, now: _at(2000)),
      isTrue,
    );

    // The shot is taken; the screen now asks for the next angle.
    expect(
      gate.isSettled(target: CaptureAngle.rearRightCorner, now: _at(2000)),
      isFalse,
      reason: 'a tap straight after the shot would photograph the rear-right '
          'corner from where the right side was taken',
    );

    gate.update(target: CaptureAngle.rearRightCorner, ready: true, now: _at(2010));
    expect(
      gate.isSettled(target: CaptureAngle.rearRightCorner, now: _at(2609)),
      isFalse,
    );
    expect(
      gate.isSettled(target: CaptureAngle.rearRightCorner, now: _at(2610)),
      isTrue,
    );
  });

  test('nothing left to shoot never settles', () {
    final gate = HoldSteady(_window)
      ..update(target: null, ready: true, now: _at(0));

    expect(gate.isSettled(target: null, now: _at(5000)), isFalse);
  });

  test('a camera that has just opened starts the window over', () {
    final gate = HoldSteady(_window)
      ..update(target: CaptureAngle.front, ready: true, now: _at(0))
      ..restart()
      ..update(target: CaptureAngle.front, ready: true, now: _at(700));

    expect(gate.isSettled(target: CaptureAngle.front, now: _at(1299)), isFalse);
    expect(gate.isSettled(target: CaptureAngle.front, now: _at(1300)), isTrue);
  });
}
