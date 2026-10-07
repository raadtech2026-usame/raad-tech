import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/auth/auth_state.dart';
import '../core/auth/principal.dart';
import '../core/l10n/strings.dart';
import '../core/theme/theme_mode.dart';
import '../features/admin/admin_screens.dart';
import '../features/auth/change_password_screen.dart';
import '../features/auth/login_screen.dart';
import '../features/driver/driver_screens.dart';
import '../features/parent/parent_screens.dart';
import '../shared/widgets.dart';

/// One app, three experiences: parent, driver, organization admin (ADR-0062). The role comes
/// from the server at sign-in; a `Principal` has exactly one role per session, so there is no
/// role switcher. Which screens show is presentation only: the server decides what each role
/// may read.
class RaadApp extends ConsumerWidget {
  const RaadApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);
    return MaterialApp(
      title: 'RAAD',
      debugShowCheckedModeBanner: false,
      theme: raadTheme(Brightness.light),
      darkTheme: raadTheme(Brightness.dark),
      themeMode: ref.watch(themeModeProvider),
      home: switch (authState) {
        AuthInitial() => const _SplashScreen(),
        AuthUnauthenticated(sessionExpired: final expired) =>
          LoginScreen(sessionExpired: expired),
        AuthAuthenticated(session: final session) =>
          homeForPrincipal(session.principal),
      },
    );
  }
}

/// Where a signed-in person lands. RAAD's own staff roles have no mobile experience.
Widget homeForPrincipal(Principal principal) {
  if (principal.isPasswordChangeRequired) return const ChangePasswordScreen();
  if (principal.isDriver) return const DriverShell();
  if (principal.isParent) return const ParentShell();
  if (principal.isOrgAdmin) return const AdminShell();
  return const UnsupportedRoleScreen();
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.surface,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset('assets/logo-raad.png', height: 84),
            const SizedBox(height: 24),
            const CircularProgressIndicator(),
          ],
        ),
      ),
    );
  }
}

class UnsupportedRoleScreen extends ConsumerWidget {
  const UnsupportedRoleScreen({super.key});

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
