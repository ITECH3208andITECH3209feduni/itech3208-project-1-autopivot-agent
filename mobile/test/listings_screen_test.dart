// Long-press on a listing card in lib/features/listings/listings_screen.dart:
// a context menu offering Archive and Delete, each behind the same kind of
// confirmation dialog the row's existing swipe-to-archive gesture already
// uses.
//
// The real risk this file exists to catch is not "does the sheet open" but
// "does adding onLongPress to the same InkWell a Dismissible already wraps
// break the drag gesture that was there first" -- so the swipe-to-archive
// regression test below runs against the exact same _ListingRow the
// long-press tests use, not a separate fixture.
//
// _FakeApi extends the real ApiClient the way capture_submission_test.dart's
// own _Server does, overriding only the three calls this screen makes, so
// everything else (dio, the error mapping on top of it) stays real and
// untested here on purpose -- this file is about the widget, not the client.
//
// Dialog and sheet transitions are settled with bounded pump(Duration) calls
// rather than pumpAndSettle(), matching medium_processing_test.dart's own
// reasoning: a shimmering skeleton's AnimationController repeats forever,
// and pumpAndSettle() against one never returns.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:autopivot/api/api_client.dart';
import 'package:autopivot/api/models/vehicle_listing.dart';
import 'package:autopivot/auth/auth_controller.dart';
import 'package:autopivot/features/listings/listings_screen.dart';

const _at = '2026-09-25T09:00:00';

/// `VehicleListingOut`, as api/routes_listings.py serialises it.
VehicleListing _listing(int id, String title) => VehicleListing.fromJson({
  'id': id,
  'stock_number': null,
  'title': title,
  'make': 'Mazda',
  'model': 'CX-5',
  'year': 2021,
  'variant': null,
  'price': null,
  'status': 'draft',
  'processing_status': 'pending',
  'image_count': 3,
  'created_at': _at,
  'updated_at': _at,
});

/// Stands in for the server at the client's own method boundary -- the
/// shape capture_submission_test.dart's _Server uses -- rather than at
/// dio's transport, since nothing here needs the real error mapping dio
/// sits in front of.
class _FakeApi extends ApiClient {
  _FakeApi(this.rows) : super(baseUrl: 'http://autopivot.invalid');

  List<VehicleListing> rows;

  /// (listingId, status), for every PATCH this screen asked for, in order.
  final statusChanges = <(int, String)>[];

  /// Listing ids this screen asked to DELETE, in order.
  final deleted = <int>[];

  @override
  Future<List<VehicleListing>> listings({
    int limit = 100,
    int offset = 0,
    String? query,
    String? processingStatus,
  }) async => rows;

  @override
  Future<VehicleListing> updateListingStatus(
    int listingId,
    String status,
  ) async {
    statusChanges.add((listingId, status));
    return rows.firstWhere((l) => l.id == listingId);
  }

  @override
  Future<void> deleteListing(int listingId) async {
    deleted.add(listingId);
  }
}

/// Flushes the microtasks the fake's own async methods resolve on, without
/// advancing real time -- the loading state's skeleton has no ticker of its
/// own, so nothing here needs a timed pump yet.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(Duration.zero);
  }
}

/// A finite UI animation (a sheet or dialog opening or closing) running to
/// completion -- see this file's own top comment for why not
/// pumpAndSettle().
Future<void> _transition(WidgetTester tester) async {
  await tester.pump();
  for (var i = 0; i < 5; i++) {
    await tester.pump(const Duration(milliseconds: 200));
  }
  await _settle(tester);
}

Future<_FakeApi> _pumpListings(
  WidgetTester tester,
  List<VehicleListing> rows,
) async {
  final api = _FakeApi(rows);
  final container = ProviderContainer(
    overrides: [apiClientProvider.overrideWithValue(api)],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: ListingsScreen()),
    ),
  );
  await _settle(tester);
  return api;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'long-pressing a listing card opens a menu with a findable Delete '
    'option',
    (tester) async {
      await _pumpListings(tester, [_listing(1, 'Alpha wagon')]);

      await tester.longPress(find.text('Alpha wagon'));
      await _transition(tester);

      expect(find.text('Delete listing'), findsOneWidget);
      // Not a hard requirement on its own, but Archive is already a per-row
      // action elsewhere on this same card (the swipe gesture) -- see the
      // task's own note on offering it here too.
      expect(find.text('Archive listing'), findsOneWidget);
    },
  );

  testWidgets(
    'tapping Delete in the menu goes through a confirmation dialog before '
    'anything is deleted, and Cancel leaves the listing untouched',
    (tester) async {
      final api = await _pumpListings(tester, [_listing(1, 'Alpha wagon')]);

      await tester.longPress(find.text('Alpha wagon'));
      await _transition(tester);
      await tester.tap(find.text('Delete listing'));
      await _transition(tester);

      // The dialog's own heading, not a second hit on the sheet row that
      // already closed.
      expect(find.text('Delete "Alpha wagon"?'), findsOneWidget);
      expect(api.deleted, isEmpty);

      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel'));
      await _transition(tester);
      expect(api.deleted, isEmpty);
      expect(find.text('Alpha wagon'), findsOneWidget);

      await tester.longPress(find.text('Alpha wagon'));
      await _transition(tester);
      await tester.tap(find.text('Delete listing'));
      await _transition(tester);
      await tester.tap(find.widgetWithText(FilledButton, 'Delete listing'));
      await _transition(tester);

      expect(api.deleted, [1]);
      expect(find.text('Alpha wagon'), findsNothing);
    },
  );

  testWidgets(
    'the pre-existing swipe-to-archive gesture still works on a row that '
    'now also carries a long-press handler',
    (tester) async {
      final api = await _pumpListings(tester, [_listing(1, 'Alpha wagon')]);

      await tester.drag(find.text('Alpha wagon'), const Offset(-500, 0));
      await _transition(tester);

      expect(find.text('Archive Alpha wagon?'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Archive'));
      await _transition(tester);

      expect(api.statusChanges, [(1, 'archived')]);
      expect(find.text('Alpha wagon'), findsNothing);
    },
  );
}
