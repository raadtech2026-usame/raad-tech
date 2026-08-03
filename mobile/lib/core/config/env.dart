/// API/WebSocket base URLs. Priority 1 Item 9 (PROJECT_STATUS.md) / Phase M0.
///
/// Compile-time constants (`--dart-define`), mirroring the web dashboard's own build-time
/// `VITE_API_BASE_URL`/`VITE_WS_BASE_URL` convention (ADR-0011) rather than a runtime config
/// file — same reasoning: these differ per build (dev/staging/prod), never per user, so baking
/// them in at build time is correct, not a shortcut.
///
/// Example (local dev, against the Docker Compose stack's nginx gateway):
///   flutter run \
///     --dart-define=API_BASE_URL=http://10.0.2.2/api/v1 \
///     --dart-define=WS_BASE_URL=ws://10.0.2.2
/// `10.0.2.2` is the Android emulator's own alias for the host machine's `localhost` — iOS
/// simulators can use `localhost` directly. A real device needs the host's real LAN IP or a
/// real deployed domain (see docs/runbooks/vps-deployment.md).
class Env {
  const Env._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2/api/v1',
  );

  static const String wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL',
    defaultValue: 'ws://10.0.2.2',
  );
}
