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

  const NotificationsScreen({
    super.key,
    required this.splitByKind,
    this.onOpenTransport,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final value = ref.watch(notificationsProvider);
    void refresh() => ref.invalidate(notificationsProvider);

    Widget list(List<AppNotification> items) {
      if (items.isEmpty) {
        return EmptyView(
          icon: Icons.notifications_none_rounded,
          message: s.noNotifications,
        );
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
          value: value,
          onRetry: refresh,
          builder: list,
        ),
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
                text: s.transportTab,
              ),
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
    if (notification.isSafety) {
      return Icons.warning_amber_rounded;
    }
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
    final isSafety = n.isSafety;
    // The server writes English. Known transport events are shown in the app's language;
    // anything the office wrote itself is shown exactly as written.
    final title = s.notificationTitle(
      n.type,
      n.kind,
      n.title,
      alarmType: n.alarmType,
    );
    final body = n.body.isNotEmpty
        ? n.body
        : (s.notificationBody(n.type, n.kind, alarmType: n.alarmType) ?? '');
    final iconColor = (isSafety || isCancelled)
        ? RaadColors.red
        : RaadColors.blue;

    return SectionCard(
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_icon, color: iconColor),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (isSafety) ...[
                  Container(
                    margin: const EdgeInsets.only(bottom: 6),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: RaadColors.red.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                        color: RaadColors.red.withValues(alpha: 0.35),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.videocam_rounded,
                          size: 14,
                          color: RaadColors.red,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          s.safetyAdasBadge,
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            color: RaadColors.red,
                            letterSpacing: 0.2,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 15.5,
                    fontWeight: n.isRead ? FontWeight.w500 : FontWeight.w800,
                    color: isSafety ? RaadColors.red : null,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  body,
                  style: TextStyle(
                    color: context.colors.onSurface.withValues(alpha: 0.82),
                  ),
                ),
                if (isSafety && n.vehicleId != null) ...[
                  const SizedBox(height: 8),
                  InkWell(
                    onTap: onTap,
                    borderRadius: BorderRadius.circular(6),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: RaadColors.blue.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(
                          color: RaadColors.blue.withValues(alpha: 0.3),
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.videocam_outlined,
                            size: 15,
                            color: RaadColors.blue,
                          ),
                          const SizedBox(width: 5),
                          Text(
                            s.watchLiveCctv,
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: RaadColors.blue,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 6),
                Text(
                  friendlyMoment(n.createdAt, s),
                  style: TextStyle(fontSize: 12, color: context.muted),
                ),
              ],
            ),
          ),
          if (!n.isRead)
            Padding(
              padding: const EdgeInsets.only(left: 8, top: 4),
              child: CircleAvatar(
                radius: 4,
                backgroundColor: isSafety ? RaadColors.red : RaadColors.blue,
              ),
            ),
        ],
      ),
    );
  }
}
