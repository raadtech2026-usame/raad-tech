import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/auth/auth_state.dart';
import '../features/auth/login_screen.dart';
import '../features/driver/driver_home_screen.dart';
import '../features/parent/parent_home_screen.dart';

/// Role-based app shell (Phase M0 exit criteria: "a role-based shell rendering 'signed in as
/// Parent/Driver'"; `.claude/rules/flutter.md` #1: "One codebase, two role experiences...
/// no admin features on mobile"). No third branch exists for any other role — a token
/// authenticating a non-Parent/Driver principal is a backend/config error this app cannot
/// reach in practice (`/auth/login` is reachable by every role, but only Parent/Driver have
/// any reason to hold this app's own client credentials), and is treated as unauthenticated
/// rather than silently rendering an empty/wrong screen.
class RaadApp extends ConsumerWidget {
  const RaadApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);

    return MaterialApp(
      title: 'RAAD',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        // Brand colors per CLAUDE.md's "Design source" section (blue #1E63FF / green
        // #2FBF4F) - the full token set (§3.1/§6 of the Flutter roadmap) maps design tokens
        // into ThemeData as its own dedicated piece of work; this is the minimal seed so the
        // app doesn't render on Material's own default purple.
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1E63FF)),
        useMaterial3: true,
      ),
      home: switch (authState) {
        AuthInitial() => const _SplashScreen(),
        AuthUnauthenticated() => const LoginScreen(),
        AuthAuthenticated(session: final session) when session.principal.isDriver =>
          const DriverHomeScreen(),
        AuthAuthenticated(session: final session) when session.principal.isParent =>
          const ParentHomeScreen(),
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
      body: Center(child: CircularProgressIndicator()),
    );
  }
}

class _UnsupportedRoleScreen extends StatelessWidget {
  const _UnsupportedRoleScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'This account\'s role is not supported by the RAAD mobile app. '
            'Parent and Driver accounts only — sign in to the RAAD web dashboard instead.',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
