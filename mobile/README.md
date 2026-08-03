# Mobile — RAAD Flutter App

Single Flutter codebase (Android + iOS) rendering two role experiences via RBAC: **Parent** and
**Driver**. No admin features and no live video on mobile (video is Org Admin-only, web dashboard
only).

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §9;
`docs/architecture/frontend-flutter-master-roadmap.md` §5 (Phases M0–M5) is the approved,
phase-by-phase implementation plan this directory follows.

## Structure (as actually built)

```
lib/
├── main.dart
├── app/
│   └── app.dart               # role-based shell: Login / Driver home / Parent home
├── core/
│   ├── auth/                  # Principal, AuthSession, AuthRepository, AuthController (Riverpod)
│   ├── config/env.dart        # API/WS base URLs (--dart-define, mirrors the web's VITE_* pattern)
│   ├── network/                # ApiClient (REST + error envelope), TrackingWebSocketClient
│   └── storage/                # SecureTokenStorage (refresh token only — flutter.md #5)
├── features/
│   ├── auth/login_screen.dart # shared by both roles
│   ├── driver/                 # trip list (org-scoped) + start/end (Phase M2)
│   └── parent/                 # live tracking (Phase M3 — see "Known gaps" below)
├── shared/                     # not yet populated — reserved for cross-role widgets once a
│                               # second one is actually needed (no premature abstraction)
└── data/                       # not yet populated — reserved for Phase M5's local/offline cache
```

Feature-first, not the originally-sketched top-level `data/`/`shared/` split this README used to
describe: each feature owns its own repository (`features/driver/trip_repository.dart`,
mirroring `.claude/rules/flutter.md` #5's presentation→domain→data layering at the feature
level rather than one shared top-level `data/` folder) — a deliberate organizational choice,
flagged here rather than silently diverging from the original sketch.

## Important clarification

Live location originates from the **bus MDVR/GPS terminal**, not the phone. The Driver app is a
control/UI client (start/end trips, view assignments) — it does not stream the phone's GPS as the
tracking source. `POST /trips/{id}/start`/`/end` are pure state-machine commands.

## Layering

Clean architecture: presentation (screens + Riverpod state) → domain (the plain Dart models in
each feature, e.g. `Trip`) → data (`ApiClient`/`TrackingWebSocketClient`/per-feature repositories).

## Status (Priority 1 Item 9, `PROJECT_STATUS.md`)

**Phase M0 (Flutter Foundation) — code complete.** Riverpod state management, `flutter_secure_
storage`-backed refresh-token storage (access token in memory only), a REST client mapping the
backend's standard error envelope, a `/ws/tracking`-protocol-correct WebSocket client, and a
role-based shell (Login → Driver home / Parent home, based on the real `principal.role` from
`POST /auth/login`).

**Phase M2 (Driver Experience) — code complete, one disclosed limitation.** Lists every trip in
the driver's own organization (already tenant-scoped server-side, ADR-0021) rather than "my
trips only" — no backend endpoint exists yet to resolve a driver's own `Driver.id` from their
`Principal.user_id` (`features/driver/trip_repository.dart`'s own docstring has the full
explanation). Start/End call the real endpoints, and the **server** independently enforces
"Driver (own)" regardless of what this screen displays, so this is a UX gap, not a safety one.

**Phase M3 (Parent Experience) — partially blocked on a real, newly-discovered backend gap.**
`features/parent/live_tracking_screen.dart` is a complete, protocol-correct `/ws/tracking`
client (the active-trip-only safety behavior `.claude/rules/flutter.md` #4 requires). The
"assigned children" list this phase's own scope names first, however, has **no safe backend
endpoint to call at all** today — not just "no mobile screen for it yet." See
`docs/PROJECT_STATUS.md`'s Known Issues for the full writeup; `parent_home_screen.dart`'s own
docstring explains it in the code itself, and offers a manual "track a vehicle by id" entry
point as an explicitly-labeled stand-in for testing/demonstration, not the intended production UX.

**Phase M4 (Push notifications / FCM) — not started.** Needs a real Firebase project (a
`google-services.json`/`GoogleService-Info.plist` and real API keys), which does not exist in
this engagement — the identical category of external dependency Priority 1 Item 8 (Payment)
already carries for a real EVC Plus account. Adding the `firebase_messaging` dependency with no
real project to configure it against would be dead weight, not a working feature.

**Phase M5 (Offline resilience & mobile CI/release) — CI mechanism only.**
`.github/workflows/mobile-pipeline.yml` (checkout → `flutter pub get` → `flutter analyze` →
`dart format --set-exit-if-changed` → `flutter test`) is real and mirrors `backend-pipeline.
yml`'s own shape, but is **not live-tested against a real GitHub Actions run** — no Flutter SDK
in this sandbox at all (see below). Offline caching and the app-store release process itself are
not attempted — the latter needs real Play Store/App Store Connect accounts, another genuine
external dependency, and the former is only meaningful once M2/M3 are functionally complete
against a resolved backend (see the M3 gap above).

## Testing limitation — the most severe of any Priority 1 item, disclosed plainly

**No Flutter/Dart SDK exists anywhere in the sandbox this code was written in** (`flutter`/`dart`
resolve to nothing on `PATH`). Unlike every other Priority 1 item this program shipped — which
each still had *some* independent verification path even without their full target environment
(YAML structurally parsed for Docker Compose changes, a live DI container built and inspected
for backend wiring, real HTTP requests against a running `uvicorn` server) — **none of the Dart
code in this directory has been parsed, analyzed, compiled, or run in any way.** Every file was
written and manually re-reviewed against this repository's own actual, verified backend API
shapes (request/response JSON fields checked directly against the FastAPI schemas and route
implementations, not assumed) and against `flutter_riverpod`/`flutter_secure_storage`/
`web_socket_channel`/`flutter_test`'s documented, stable public APIs — but "carefully reviewed
by a human-equivalent read" is a categorically weaker guarantee than "compiled and tested," and
this file says so plainly rather than implying otherwise. One real bug (`/auth/logout` called
without the bearer token it actually requires) was caught during this same manual review and
fixed before commit — a proof this review process has real value, not a substitute for it.

**Before this code is trusted**: install the Flutter SDK matching `pubspec.yaml`'s constraints,
run `flutter pub get`, `flutter analyze`, `flutter test`, and `flutter run` against a real
backend (`../backend`, already running per `docker/README.md`) on an emulator/device. Treat
every M0–M3 "code complete" claim above as "written, not yet verified" until that first real
build succeeds.
