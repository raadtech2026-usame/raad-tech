import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:raad_mobile/features/auth/login_screen.dart';

/// Phase M0's own testing scope: "Widget tests (Flutter's own `flutter_test`) for the shell/
/// auth flow." Covers the login form's static shape only — no real network call is made
/// (`ApiClient`'s default `http.Client` would attempt a real request, which has nothing to
/// reach in a widget-test sandbox), matching this being a widget test, not the M0 exit
/// criterion's own "real login against the backend" (that needs an actual running backend and
/// device/emulator, `integration_test`'s job, not `flutter_test`'s).
void main() {
  testWidgets('LoginScreen shows an identifier field, a password field, and a submit button',
      (tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(home: LoginScreen()),
      ),
    );

    expect(find.text('RAAD'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Email or phone number'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Password'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Sign in'), findsOneWidget);
  });

  testWidgets('Password field obscures its text', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(home: LoginScreen()),
      ),
    );

    final passwordField = tester.widget<TextField>(
      find.widgetWithText(TextField, 'Password'),
    );
    expect(passwordField.obscureText, isTrue);
  });
}
