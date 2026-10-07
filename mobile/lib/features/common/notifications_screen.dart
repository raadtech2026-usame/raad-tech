import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';

/// The signed-in person's own notifications. With [splitByKind] (parents) there are two
/// tabs, so a message about the bus is never lost among the school's own messages.
class NotificationsScreen extends ConsumerWidget {
  final bool splitByKind;

  /// Opens the tracking screen for a bus; only parents pass it.
  final void Function(AppNotification notification)? onOpenTransport;

  const NotificationsScreen(
      {super.key, required this.splitByKind, this.onOpenTransport});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final value = ref.watch(notificationsProvider);
    void refresh() => ref.invalidate(notificationsProvider);

    Widget list(List<AppNotification> items) {
      if (items.isEmpty) {
        return EmptyView(
            icon: Icons.notifications_none_rounded, message: s.noNotifications);
      }
      return RefreshIndicator(
        onRefresh: () async => refresh(),
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: items.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, index) => _NotificationTile(
            notification: items[index],
            onTap: () async {
              final n = items[index];
              if (!n.isRead) {
                try {
                  await ref.read(repositoryProvider).markRead(n.id);
                  refresh();
                } catch (_) {
                  // Reading it again later is harmless; never block opening it.
                }
              }
              if (n.isTransport) onOpenTransport?.call(n);
            },
          ),
        ),
      );
    }

    if (!splitByKind) {
      return Scaffold(
        appBar: AppBar(title: Text(s.navNotifications)),
        body: AsyncBody<List<AppNotification>>(
            value: value, onRetry: refresh, builder: list),
      );
    }
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(s.navNotifications),
          bottom: TabBar(
            tabs: [
              Tab(
                  icon: const Icon(Icons.directions_bus_rounded),
                  text: s.transportTab),
              Tab(icon: const Icon(Icons.school_rounded), text: s.schoolTab),
            ],
          ),
        ),
        body: AsyncBody<List<AppNotification>>(
          value: value,
          onRetry: refresh,
          builder: (items) => TabBarView(
            children: [
              list(items.where((n) => n.isTransport).toList()),
              list(items.where((n) => !n.isTransport).toList()),
            ],
          ),
        ),
      ),
    );
  }
}

class _NotificationTile extends ConsumerWidget {
  final AppNotification notification;
  final VoidCallback onTap;
  const _NotificationTile({required this.notification, required this.onTap});

  IconData get _icon {
    switch (notification.kind ?? notification.type) {
      case 'trip_started':
        return Icons.play_circle_outline_rounded;
      case 'trip_completed':
        return Icons.check_circle_outline_rounded;
      case 'approaching_stop':
        return Icons.near_me_rounded;
      case 'arrived_org':
        return Icons.school_rounded;
      case 'trip_cancelled':
        return Icons.cancel_outlined;
      case 'cover_assigned':
        return Icons.swap_horiz_rounded;
      default:
        return Icons.campaign_outlined;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final n = notification;
    final isCancelled = n.kind == 'trip_cancelled';
    // The server writes English. Known transport events are shown in the app's language;
    // anything the office wrote itself is shown exactly as written.
    final title = s.notificationTitle(n.type, n.kind, n.title);
    final body = s.notificationBody(n.type, n.kind) ?? n.body;
    return SectionCard(
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_icon, color: isCancelled ? RaadColors.red : RaadColors.blue),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 15.5,
                    fontWeight: n.isRead ? FontWeight.w500 : FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(body,
                    style: TextStyle(
                        color:
                            context.colors.onSurface.withValues(alpha: 0.82))),
                const SizedBox(height: 6),
                Text(
                  friendlyMoment(n.createdAt, s),
                  style: TextStyle(fontSize: 12, color: context.muted),
                ),
              ],
            ),
          ),
          if (!n.isRead)
            const Padding(
              padding: EdgeInsets.only(left: 8, top: 4),
              child: CircleAvatar(radius: 4, backgroundColor: RaadColors.blue),
            ),
        ],
      ),
    );
  }
}
