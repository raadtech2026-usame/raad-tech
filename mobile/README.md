# Mobile — RAAD Flutter app (Parent + Driver)

One Flutter app, two experiences, chosen by the role the server returns at sign-in
(`.claude/rules/flutter.md` #1). No admin features. Android first; the iOS project is generated
but has not been built.

Design records: ADR-0023 (`/me`), ADR-0026 (parent camera access), ADR-0060 (`/me/transport`),
ADR-0061 (mobile self-service).

## What each role can do

**Parent**

- Sign in, and replace a temporary password on first use.
- See each child, their bus, route, pickup stop and dropoff stop.
- See today's trips and their status: scheduled, on trip, completed, cancelled (with the reason).
- Follow the bus on a map while it is on a trip, with the distance to the family's stop.
- Notifications in two tabs: bus messages, and messages from the school.
- Trip history for the last 30 days.
- Watch the bus camera, only if the school granted it (ADR-0026).

**Driver**

- Sign in; see only their own trips: today, upcoming and past.
- Start and end a trip. The server refuses another driver's trip.
- Trip details: stops in order, students with their stops, the crew.
- See a cancelled trip and its reason; see when they are covering for another driver.
- Report days they cannot work, and withdraw them until cover is arranged.
- Report an incident and follow the status of their own reports.
- See their own documents and whether anything required is missing.

The driver's phone is never a tracking source. The bus's terminal is
(`.claude/rules/flutter.md` #2); the app requests no location permission.

## What the app does not claim

- **No boarding record exists.** History says a trip ran or was cancelled. It never says a
  child boarded or missed the bus.
- **No ETA.** The backend has none. The tracking screen shows the straight-line distance from
  the bus to the family's stop, computed from the live position.
- **Live position only during a trip.** Outside one, the screen says so
  (`.claude/rules/flutter.md` #4). A position older than two minutes is marked as old.
- **No background push yet.** There is no Firebase project and the backend has no sender.
  Notifications arrive while the app is open (over `/ws/notifications`) and are listed when it
  is reopened. `core/push/push_service.dart` is the single place a Firebase implementation
  plugs in.

## Structure

```
lib/
├── main.dart
├── app/app.dart                 # role routing: login / change password / parent / driver
├── core/
│   ├── auth/                    # session, sign-in, automatic refresh on 401
│   ├── config/env.dart          # --dart-define values; refuses plain HTTP in a release build
│   ├── data/                    # models.dart (wire shapes), repository.dart (calls + providers)
│   ├── l10n/strings.dart        # Somali (default) and English
│   ├── network/                 # ApiClient, tracking and notification sockets
│   ├── push/                    # PushService seam (no-op today)
│   ├── storage/                 # refresh token in secure storage
│   └── util/format.dart         # dates, distance
├── shared/widgets.dart          # theme, loading/error/empty views, cards
└── features/
    ├── auth/                    # login, change password
    ├── common/                  # notifications, profile
    ├── map/bus_map.dart         # map behind a tile-source seam (Mapbox tiles, ADR-0011)
    ├── parent/                  # home, live tracking, history
    ├── driver/                  # today, trips, trip detail, self-service
    └── video/                   # parent camera player (ADR-0026)
```

State is Riverpod. The access token is held in memory only; the refresh token is in
`flutter_secure_storage`. Every data call is self-scoped on the server: the app never sends an
id that says who the caller is.

## Build

```
flutter pub get
flutter analyze
flutter test

# Debug build against a backend on the development machine (emulator -> host is 10.0.2.2):
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1 \
            --dart-define=WS_BASE_URL=ws://10.0.2.2:8000

# Release APK. HTTPS and WSS are required; the app refuses to sign in otherwise.
flutter build apk --release \
  --dart-define=API_BASE_URL=https://<api-host>/api/v1 \
  --dart-define=WS_BASE_URL=wss://<api-host> \
  --dart-define=MAPBOX_ACCESS_TOKEN=<public pk. token>
```

Without `MAPBOX_ACCESS_TOKEN` the tracking screen shows the position as text instead of a map.

The release build is signed with the debug key unless `android/key.properties` exists (see
`android/key.properties.example`). A debug-signed APK installs for testing but cannot be
published or updated in place by a differently signed build.
