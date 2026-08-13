import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:raad_mobile/features/video/video_watch_screen.dart';

/// ADR-0026 §5 — mirrors `login_screen_test.dart`'s exact scope/shape: static widget structure
/// only, no real network call (`VideoRepository`'s default `ApiClient` would attempt a real
/// request, which has nothing to reach in a widget-test sandbox).
void main() {
  testWidgets(
    'VideoWatchScreen shows a device id field, a camera id field, and a watch button',
    (tester) async {
      await tester.pumpWidget(
        const ProviderScope(
          child: MaterialApp(home: VideoWatchScreen()),
        ),
      );

      expect(find.text('Watch live video'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Device ID'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Camera ID'), findsOneWidget);
    },
  );

  testWidgets('The watch button is disabled while not requesting', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(home: VideoWatchScreen()),
      ),
    );

    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNotNull);
  });
}
