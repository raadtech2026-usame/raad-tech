import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n/strings.dart';
import '../core/network/api_exception.dart';

/// RAAD brand colours (the web dashboard's `styles/tokens.css`).
class RaadColors {
  const RaadColors._();
  static const blue = Color(0xFF1E63FF);
  static const green = Color(0xFF2FBF4F);
  static const amber = Color(0xFFE08A00);
  static const red = Color(0xFFD93025);
  static const grey = Color(0xFF6B7280);
}

ThemeData raadTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: RaadColors.blue);
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: const Color(0xFFF5F7FB),
    appBarTheme: AppBarTheme(
      backgroundColor: scheme.surface,
      foregroundColor: scheme.onSurface,
      elevation: 0,
      scrolledUnderElevation: 1,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: Colors.white,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Color(0xFFE5E9F2)),
      ),
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
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
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
            ?.copyWith(color: RaadColors.grey, fontWeight: FontWeight.w700),
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
            Icon(icon, size: 48, color: RaadColors.grey),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 15, color: RaadColors.grey),
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
              color: RaadColors.grey,
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
