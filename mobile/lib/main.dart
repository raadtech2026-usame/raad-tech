import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';

import 'app/app.dart';

void main() {
  // ADR-0026 §5: one-time native libmpv init `media_kit`'s own docs require before
  // constructing any `Player` — must run before `runApp`, cheap/idempotent if the video
  // feature is never actually opened this session (a Parent with no video grant).
  MediaKit.ensureInitialized();
  runApp(const ProviderScope(child: RaadApp()));
}
