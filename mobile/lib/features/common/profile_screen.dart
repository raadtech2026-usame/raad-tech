import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_repository.dart';
import '../../core/auth/auth_state.dart';
import '../../core/l10n/strings.dart';
import '../../core/theme/theme_mode.dart';
import '../../shared/widgets.dart';

/// The signed-in person's own account, the language choice and sign-out. [extra] lets a role
/// add its own entries above the language choice (the driver's self-service links).
class ProfileScreen extends ConsumerWidget {
  final String title;
  final List<Widget> extra;
  const ProfileScreen({super.key, required this.title, this.extra = const []});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final language = ref.watch(languageProvider);
    final themeMode = ref.watch(themeModeProvider);
    final profile = ref.watch(userProfileProvider);
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            child: profile.when(
              loading: () => const SizedBox(height: 72, child: LoadingView()),
              error: (error, _) => Text(errorMessage(error, s)),
              data: (UserProfile user) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user.fullName,
                    style: const TextStyle(
                        fontSize: 20, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  StatusChip(
                    label: s.roleName(user.role),
                    color: RaadColors.blue,
                  ),
                  const SizedBox(height: 8),
                  if (user.phone != null)
                    InfoRow(
                        icon: Icons.phone_rounded,
                        label: s.phone,
                        value: user.phone!),
                  if (user.email != null)
                    InfoRow(
                        icon: Icons.mail_outline_rounded,
                        label: s.email,
                        value: user.email!),
                ],
              ),
            ),
          ),
          ...extra,
          SectionTitle(s.language),
          SectionCard(
            child: SegmentedButton<String>(
              segments: [
                ButtonSegment(value: 'so', label: Text(s.somali)),
                ButtonSegment(value: 'en', label: Text(s.english)),
              ],
              selected: {language},
              showSelectedIcon: false,
              onSelectionChanged: (value) =>
                  ref.read(languageProvider.notifier).state = value.first,
            ),
          ),
          SectionTitle(s.appearance),
          SectionCard(
            child: SegmentedButton<ThemeMode>(
              segments: [
                ButtonSegment(
                    value: ThemeMode.system, label: Text(s.themeSystem)),
                ButtonSegment(
                    value: ThemeMode.light, label: Text(s.themeLight)),
                ButtonSegment(value: ThemeMode.dark, label: Text(s.themeDark)),
              ],
              selected: {themeMode},
              showSelectedIcon: false,
              onSelectionChanged: (value) =>
                  ref.read(themeModeProvider.notifier).set(value.first),
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              foregroundColor: RaadColors.red,
            ),
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
            icon: const Icon(Icons.logout_rounded),
            label: Text(s.signOut),
          ),
        ],
      ),
    );
  }
}
