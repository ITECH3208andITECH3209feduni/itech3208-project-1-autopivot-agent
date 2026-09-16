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
///
/// Backed by a disk cache ([_diskCached]) on top of the in-memory one below:
/// a stored photograph's bytes never change once uploaded — [storagePath] is
/// content-addressed — so there is nothing to invalidate, only a first fetch
/// to avoid repeating on every cold start. Without it, reopening a listing
/// you looked at yesterday re-downloads every photograph again before
/// showing a single pixel.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../api/api_client.dart';
import '../auth/auth_controller.dart';
import 'skeleton.dart';

/// A stored path is `/api/files/{dealership}/{listing}/{file}` — replacing
/// its slashes is enough to make a valid, collision-free filename, since the
/// path itself is already unique per photograph.
String _cacheKey(String storagePath) =>
    storagePath.replaceAll('/', '_').replaceAll(RegExp(r'^_+'), '');

Future<Directory> _imageCacheDir() async {
  // The OS-managed cache directory, not documents: this is exactly what that
  // distinction is for — content worth keeping around for speed, never
  // backed up, and the platform is free to reclaim it under storage
  // pressure without this app needing to know or care.
  final base = await getApplicationCacheDirectory();
  final dir = Directory('${base.path}/image_cache');
  if (!await dir.exists()) await dir.create(recursive: true);
  return dir;
}

/// Reads [storagePath]'s bytes from disk if a prior fetch already cached
/// them, fetching and caching them via [api] otherwise.
Future<Uint8List> _diskCached(ApiClient api, String storagePath) async {
  final dir = await _imageCacheDir();
  final file = File('${dir.path}/${_cacheKey(storagePath)}');

  if (await file.exists()) {
    try {
      return await file.readAsBytes();
    } catch (_) {
      // A corrupt or partially-written cache entry is not worth diagnosing —
      // just refetch as though it were never cached.
    }
  }

  final bytes = await api.fileBytes(storagePath);
  try {
    await file.writeAsBytes(bytes, flush: true);
  } catch (_) {
    // Caching is an optimisation, not a requirement — a write failure (full
    // disk, a sandbox restriction) should not turn a successful fetch into a
    // visible error.
  }
  return bytes;
}

/// Decoded bytes, keyed by storage path.
///
/// `autoDispose` would refetch every time a tile scrolled out of view and back,
/// which on a gallery is a lot of round trips for bytes that have not changed —
/// stored files are content-addressed, so a path's contents never change. The
/// disk cache in [_diskCached] carries that same guarantee across cold starts,
/// where this in-memory one cannot help at all.
final _imageBytesProvider = FutureProvider.family<Uint8List, String>((
  ref,
  path,
) async {
  final api = ref.watch(apiClientProvider);
  return _diskCached(api, path);
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

/// Self-contained rather than reading a [ShimmerGroup] from context: a
/// photograph can be the first thing loading on a screen that has already
/// finished its own skeleton state (an image whose bytes have not arrived
/// yet on an otherwise-loaded listing), so it cannot assume one is already
/// above it in the tree.
class _Placeholder extends StatelessWidget {
  const _Placeholder();

  @override
  Widget build(BuildContext context) {
    return const ShimmerGroup(
      child: SizedBox.expand(
        child: SkeletonBox(borderRadius: BorderRadius.zero),
      ),
    );
  }
}
