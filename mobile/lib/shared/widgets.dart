import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n/strings.dart';
import '../core/network/api_exception.dart';

/// RAAD colours, taken from the web dashboard's `frontend/src/styles/tokens.css` so the app and
/// the dashboard read as one product. The status colours are the same in light and dark.
class RaadColors {
  const RaadColors._();
  static const blue = Color(0xFF1E63FF); // --color-brand-primary
  static const green = Color(0xFF10B981); // --color-success
  static const amber = Color(0xFFF59E0B); // --color-warning
  static const red = Color(0xFFEF4444); // --color-danger

  /// Secondary text on a light surface. Screens should prefer `context.muted`, which follows
  /// the theme; this stays for the few places that draw on a fixed light background.
  static const grey = Color(0xFF64748B); // --color-text-muted
}

extension RaadThemeContext on BuildContext {
  ColorScheme get colors => Theme.of(this).colorScheme;

  /// Secondary text: `--color-text-muted` in the current theme.
  Color get muted => colors.onSurfaceVariant;
}

/// The app's theme in the web dashboard's light or dark tokens (`[data-theme="dark"]`).
ThemeData raadTheme([Brightness brightness = Brightness.light]) {
  final dark = brightness == Brightness.dark;
  final primary = dark ? const Color(0xFF3B82F6) : RaadColors.blue;
  final canvas = dark ? const Color(0xFF090D16) : const Color(0xFFF4F6FA);
  final surface = dark ? const Color(0xFF111827) : Colors.white;
  final subtle = dark ? const Color(0xFF162032) : const Color(0xFFF8FAFC);
  final border = dark ? const Color(0x17FFFFFF) : const Color(0xFFE2E8F0);
  final inputBorder = dark ? const Color(0x29FFFFFF) : const Color(0xFFCBD5E1);
  final text = dark ? const Color(0xFFF8FAFC) : const Color(0xFF0F172A);
  final muted = dark ? const Color(0xFF94A3B8) : const Color(0xFF64748B);
  final primaryTint = dark ? const Color(0x473B82F6) : const Color(0xFFDBE7FF);

  final scheme =
      ColorScheme.fromSeed(seedColor: RaadColors.blue, brightness: brightness)
          .copyWith(
    primary: primary,
    onPrimary: Colors.white,
    secondary: RaadColors.green,
    secondaryContainer: primaryTint,
    onSecondaryContainer: dark ? const Color(0xFFDBE7FF) : RaadColors.blue,
    error: RaadColors.red,
    surface: surface,
    onSurface: text,
    onSurfaceVariant: muted,
    surfaceContainerLowest: surface,
    surfaceContainerLow: surface,
    surfaceContainer: surface,
    surfaceContainerHigh: subtle,
    surfaceContainerHighest: subtle,
    outline: inputBorder,
    outlineVariant: border,
  );
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: canvas,
    dividerTheme: DividerThemeData(color: border, thickness: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: surface,
      foregroundColor: text,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 1,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: surface,
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: border),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      indicatorColor: primaryTint,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: inputBorder),
      ),
    ),
  );
}

Color tripStatusColor(String status) {
  switch (status) {
    case 'in_progress':
      return RaadColors.green;
    case 'scheduled':
      return RaadColors.blue;
    case 'cancelled':
      return RaadColors.red;
    case 'interrupted':
      return RaadColors.amber;
    default:
      return RaadColors.grey;
  }
}

class StatusChip extends StatelessWidget {
  final String label;
  final Color color;
  const StatusChip({super.key, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
            color: color, fontSize: 12.5, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class SectionCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  const SectionCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final content = Padding(padding: padding, child: child);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: onTap == null ? content : InkWell(onTap: onTap, child: content),
    );
  }
}

class SectionTitle extends StatelessWidget {
  final String text;
  const SectionTitle(this.text, {super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 20, 4, 8),
      child: Text(
        text,
        style: Theme.of(context)
            .textTheme
            .titleSmall
            ?.copyWith(color: context.muted, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const InfoRow(
      {super.key,
      required this.icon,
      required this.label,
      required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: RaadColors.blue),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(
                        fontSize: 12.5, color: RaadColors.grey)),
                const SizedBox(height: 2),
                Text(value,
                    style: const TextStyle(
                        fontSize: 15.5, fontWeight: FontWeight.w600)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) =>
      const Center(child: CircularProgressIndicator());
}

class EmptyView extends StatelessWidget {
  final IconData icon;
  final String message;
  const EmptyView({super.key, required this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: context.muted),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 15, color: context.muted),
            ),
          ],
        ),
      ),
    );
  }
}

/// What a person can read when a request fails: offline is said plainly, a server message is
/// shown as the server wrote it, anything else is a generic line. Always with a way to retry.
class ErrorView extends ConsumerWidget {
  final Object error;
  final VoidCallback onRetry;
  const ErrorView({super.key, required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isOffline(error)
                  ? Icons.wifi_off_rounded
                  : Icons.error_outline_rounded,
              size: 48,
              color: context.muted,
            ),
            const SizedBox(height: 12),
            Text(
              errorMessage(error, s),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 15),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(s.retry),
            ),
          ],
        ),
      ),
    );
  }
}

bool isOffline(Object error) => error is ApiException && error.isNetwork;

String errorMessage(Object error, Strings s) {
  if (error is ApiException) {
    return error.isNetwork ? s.noConnection : error.message;
  }
  return s.somethingWrong;
}

void showError(BuildContext context, Object error, Strings s) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(errorMessage(error, s))));
}

/// The standard body for a list or detail backed by one request.
class AsyncBody<T> extends StatelessWidget {
  final AsyncValue<T> value;
  final VoidCallback onRetry;
  final Widget Function(T data) builder;
  const AsyncBody(
      {super.key,
      required this.value,
      required this.onRetry,
      required this.builder});

  @override
  Widget build(BuildContext context) {
    return value.when(
      skipLoadingOnRefresh: true,
      data: builder,
      loading: () => const LoadingView(),
      error: (error, _) => ErrorView(error: error, onRetry: onRetry),
    );
  }
}

Future<bool> confirm(BuildContext context,
    {required String title, required Strings s}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(s.cancel)),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(96, 44)),
          onPressed: () => Navigator.pop(context, true),
          child: Text(s.confirm),
        ),
      ],
    ),
  );
  return result ?? false;
}
