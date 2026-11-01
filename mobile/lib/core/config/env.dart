/// Build-time configuration, passed with `--dart-define` (mirrors the web's `VITE_*` pattern):
///
/// ```
/// flutter build apk --release \
///   --dart-define=API_BASE_URL=https://api.raadsystems.tech \
///   --dart-define=WS_BASE_URL=wss://api.raadsystems.tech/ws \
///   --dart-define=MAPBOX_ACCESS_TOKEN=pk....
/// ```
///
/// Production fallback defaults point to https://api.raadsystems.tech and
/// wss://api.raadsystems.tech/ws. They are secure HTTPS/WSS, accepted by [Env.releaseConfigurationError].
class Env {
  const Env._();

  static const String rawApiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://api.raadsystems.tech',
  );

  static const String rawWsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'wss://api.raadsystems.tech/ws',
  );

  /// Normalized API base URL ensuring the `/api/v1` prefix is cleanly present.
  static String get apiBaseUrl {
    final sanitized = rawApiBaseUrl.trim().replaceAll(RegExp(r'/+$'), '');
    if (sanitized.endsWith('/api/v1')) {
      return sanitized;
    }
    return '$sanitized/api/v1';
  }

  /// Normalized WebSocket base URL ensuring trailing `/ws` or `/` is cleanly handled
  /// before feature endpoints (`/ws/tracking`, `/ws/notifications`) are appended.
  static String get wsBaseUrl {
    var sanitized = rawWsBaseUrl.trim().replaceAll(RegExp(r'/+$'), '');
    if (sanitized.endsWith('/ws')) {
      sanitized = sanitized.substring(0, sanitized.length - 3);
    }
    return sanitized;
  }

  /// The public Mapbox token (ADR-0011, the web dashboard's provider). Empty means no map
  /// tiles: the tracking screen then shows the position as text instead of failing.
  static const String mapboxAccessToken = String.fromEnvironment(
    'MAPBOX_ACCESS_TOKEN',
  );

  /// Optional Firebase configuration passed with `--dart-define` for environments
  /// where native google-services.json / GoogleService-Info.plist is not bundled.
  static const String firebaseApiKey = String.fromEnvironment(
    'FIREBASE_API_KEY',
  );
  static const String firebaseAppId = String.fromEnvironment(
    'FIREBASE_APP_ID',
  );
  static const String firebaseMessagingSenderId = String.fromEnvironment(
    'FIREBASE_MESSAGING_SENDER_ID',
  );
  static const String firebaseProjectId = String.fromEnvironment(
    'FIREBASE_PROJECT_ID',
  );

  static bool get hasFirebaseConfig =>
      firebaseApiKey.isNotEmpty &&
      firebaseAppId.isNotEmpty &&
      firebaseProjectId.isNotEmpty;

  static const bool isRelease = bool.fromEnvironment('dart.vm.product');

  static bool get hasMap => mapboxAccessToken.isNotEmpty;

  /// A release build must not send a password or a token over plain HTTP.
  static String? get releaseConfigurationError {
    if (!isRelease) return null;
    if (!rawApiBaseUrl.startsWith('https://') ||
        !rawWsBaseUrl.startsWith('wss://')) {
      return 'This build was made without a secure server address '
          '(API_BASE_URL must be https, WS_BASE_URL must be wss).';
    }
    return null;
  }
}
