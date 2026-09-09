/// An image from `/api/files/{path}`, which requires the bearer header.
///
/// `Image.network` cannot show one of these. Flutter fetches image URLs through
/// its own loader, which attaches no `Authorization` header, so every stored
/// photograph comes back 401 and renders as a broken box. The bytes have to be
/// fetched through the same client that holds the token, which is what this
/// does. The web client has a component of the same name for the same reason.
///
/// Nothing in APA-141 displays a stored image yet — `VehicleListingOut` carries
/// an `image_count` but no URL, so a listings row has nothing to show. This
/// exists because the capture story lands next and will need it immediately,
/// and because discovering the 401 then would look like an auth bug rather
/// than a missing header.
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../auth/auth_controller.dart';
import '../design/tokens.dart';

/// Decoded bytes, keyed by storage path.
///
/// `autoDispose` would refetch every time a tile scrolled out of view and back,
/// which on a gallery is a lot of round trips for bytes that have not changed —
/// stored files are content-addressed, so a path's contents never change.
final _imageBytesProvider = FutureProvider.family<Uint8List, String>((
  ref,
  path,
) async {
  final api = ref.watch(apiClientProvider);
  return api.fileBytes(path);
});

class AuthedImage extends ConsumerWidget {
  const AuthedImage({
    super.key,
    required this.storagePath,
    required this.semanticLabel,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
  });

  /// Either a bare storage path or the full `/api/files/...` URL the API
  /// returns; [ApiClient.fileBytes] accepts both.
  final String storagePath;

  /// Required, not optional. An unlabelled photograph is invisible to a screen
  /// reader, and this is the one widget guaranteed to be used in a list.
  final String semanticLabel;

  final double? width;
  final double? height;
  final BoxFit fit;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bytes = ref.watch(_imageBytesProvider(storagePath));

    return SizedBox(
      width: width,
      height: height,
      child: bytes.when(
        data: (data) => Image.memory(
          data,
          width: width,
          height: height,
          fit: fit,
          semanticLabel: semanticLabel,
        ),
        loading: () => const _Placeholder(),
        // No message and no icon: a failed thumbnail should read as a gap, not
        // as an error the user has to act on. The screen around it reports
        // anything that actually needs attention.
        error: (_, _) => const _Placeholder(),
      ),
    );
  }
}

class _Placeholder extends StatelessWidget {
  const _Placeholder();

  @override
  Widget build(BuildContext context) {
    return const DecoratedBox(
      decoration: BoxDecoration(color: C.bone),
      child: SizedBox.expand(),
    );
  }
}
