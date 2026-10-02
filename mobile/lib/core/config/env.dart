/// Build-time configuration, passed with `--dart-define` (mirrors the web's `VITE_*` pattern):
///
/// ```
/// flutter build apk --release \
///   --dart-define=API_BASE_URL=https://api.example.com/api/v1 \
///   --dart-define=WS_BASE_URL=wss://api.example.com \
///   --dart-define=MAPBOX_ACCESS_TOKEN=pk....
/// ```
///
/// The defaults reach a backend on the development machine from the Android emulator
/// (`10.0.2.2` is the emulator's name for the host). They are plain HTTP, which a release
/// build refuses: see [Env.releaseConfigurationError].
class Env {
  const Env._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );

  static const String wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://10.0.2.2:8000',
  );

  /// The public Mapbox token (ADR-0011, the web dashboard's provider). Empty means no map
  /// tiles: the tracking screen then shows the position as text instead of failing.
  static const String mapboxAccessToken =
      String.fromEnvironment('MAPBOX_ACCESS_TOKEN');

  static const bool isRelease = bool.fromEnvironment('dart.vm.product');

  static bool get hasMap => mapboxAccessToken.isNotEmpty;

  /// A release build must not send a password or a token over plain HTTP.
  static String? get releaseConfigurationError {
    if (!isRelease) return null;
    if (!apiBaseUrl.startsWith('https://') || !wsBaseUrl.startsWith('wss://')) {
      return 'This build was made without a secure server address '
          '(API_BASE_URL must be https, WS_BASE_URL must be wss).';
    }
    return null;
  }
}
