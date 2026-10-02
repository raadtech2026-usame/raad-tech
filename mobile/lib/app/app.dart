import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/auth/auth_state.dart';
import '../core/l10n/strings.dart';
import '../features/auth/change_password_screen.dart';
import '../features/auth/login_screen.dart';
import '../features/driver/driver_screens.dart';
import '../features/parent/parent_screens.dart';
import '../shared/widgets.dart';

/// One app, two experiences. The role comes from the server at sign-in; a `Principal` has
/// exactly one role per session, so there is no role switcher.
class RaadApp extends ConsumerWidget {
  const RaadApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);
    return MaterialApp(
      title: 'RAAD',
      debugShowCheckedModeBanner: false,
      theme: raadTheme(),
      home: switch (authState) {
        AuthInitial() => const _SplashScreen(),
        AuthUnauthenticated(sessionExpired: final expired) =>
          LoginScreen(sessionExpired: expired),
        AuthAuthenticated(session: final session)
            when session.principal.isPasswordChangeRequired =>
          const ChangePasswordScreen(),
        AuthAuthenticated(session: final session)
            when session.principal.isDriver =>
          const DriverShell(),
        AuthAuthenticated(session: final session)
            when session.principal.isParent =>
          const ParentShell(),
        AuthAuthenticated() => const _UnsupportedRoleScreen(),
      },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Colors.white,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.directions_bus_rounded,
                size: 64, color: RaadColors.blue),
            SizedBox(height: 24),
            CircularProgressIndicator(),
          ],
        ),
      ),
    );
  }
}

class _UnsupportedRoleScreen extends ConsumerWidget {
  const _UnsupportedRoleScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(s.unsupportedRole, textAlign: TextAlign.center),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: () =>
                    ref.read(authControllerProvider.notifier).logout(),
                child: Text(s.signOut),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
