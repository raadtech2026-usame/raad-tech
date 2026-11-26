import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_repository.dart';
import '../../core/auth/auth_state.dart';
import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';

/// Provider that fetches the caller's own active sessions from `GET /auth/sessions`.
final sessionsProvider = FutureProvider.autoDispose<List<ActiveSession>>((ref) {
  final repo = ref.watch(authRepositoryProvider);
  return repo.listSessions();
});

/// Screen that lists all active sessions for the signed-in user and lets them
/// revoke any session (ADR-0019 — "secure device replacement flow").
class SessionsScreen extends ConsumerWidget {
  const SessionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final sessions = ref.watch(sessionsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.sessionsTitle)),
      body: sessions.when(
        loading: () => const LoadingView(),
        error: (error, _) => ErrorView(
          error: error,
          onRetry: () => ref.invalidate(sessionsProvider),
        ),
        data: (list) {
          if (list.isEmpty) {
            return EmptyView(
              icon: Icons.devices_rounded,
              message: s.noSessions,
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: list.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final session = list[index];
              return _SessionTile(
                session: session,
                revokeLabel: s.revokeSessionAction,
                onRevoke: () async {
                  final confirmed = await _confirmRevoke(context, s);
                  if (!confirmed) return;
                  try {
                    await ref
                        .read(authRepositoryProvider)
                        .revokeSession(session.id);
                    ref.invalidate(sessionsProvider);
                  } catch (e) {
                    if (context.mounted) showError(context, e, s);
                  }
                },
              );
            },
          );
        },
      ),
    );
  }

  Future<bool> _confirmRevoke(BuildContext context, Strings s) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(s.revokeSessionTitle),
        content: Text(s.revokeSessionBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(s.cancel),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: RaadColors.red,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(s.revokeSessionConfirm),
          ),
        ],
      ),
    );
    return result ?? false;
  }
}

class _SessionTile extends StatelessWidget {
  final ActiveSession session;
  final String revokeLabel;
  final VoidCallback onRevoke;
  const _SessionTile({
    required this.session,
    required this.revokeLabel,
    required this.onRevoke,
  });

  @override
  Widget build(BuildContext context) {
    final label = session.deviceLabel ?? session.ipAddress ?? '—';
    final expired = session.expiresAt.isBefore(DateTime.now());
    return SectionCard(
      child: Row(
        children: [
          Icon(
            Icons.phone_android_rounded,
            color: expired ? RaadColors.grey : RaadColors.blue,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (session.ipAddress != null && session.deviceLabel != null)
                  Text(
                    session.ipAddress!,
                    style: TextStyle(fontSize: 12, color: context.muted),
                  ),
                Text(
                  _formatDate(session.issuedAt),
                  style: TextStyle(fontSize: 12, color: context.muted),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: onRevoke,
            style: TextButton.styleFrom(foregroundColor: RaadColors.red),
            child: Text(revokeLabel),
          ),
        ],
      ),
    );
  }

  String _formatDate(DateTime dt) {
    final local = dt.toLocal();
    return '${local.year}-${local.month.toString().padLeft(2, '0')}-'
        '${local.day.toString().padLeft(2, '0')} '
        '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }
}

/// Convenience helper used in ProfileScreen.
void openSessionsScreen(BuildContext context) {
  Navigator.of(context).push<void>(
    MaterialPageRoute(builder: (_) => const SessionsScreen()),
  );
}
