import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';

import 'app/app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // ADR-0026 §5: `media_kit` needs its native player initialised before any `Player` exists.
  // Cheap when the camera feature is never opened (a parent with no video grant).
  MediaKit.ensureInitialized();
  runApp(const ProviderScope(child: RaadApp()));
}
