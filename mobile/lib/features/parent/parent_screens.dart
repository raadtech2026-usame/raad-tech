import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../common/notifications_screen.dart';
import '../common/profile_screen.dart';
import '../video/video_providers.dart';
import '../video/video_watch_screen.dart';
import 'live_tracking_screen.dart';

/// The Parent experience: Home (the child's bus), History, Notifications, Account.
class ParentShell extends ConsumerStatefulWidget {
  const ParentShell({super.key});

  @override
  ConsumerState<ParentShell> createState() => _ParentShellState();
}

class _ParentShellState extends ConsumerState<ParentShell> {
  int _index = 0;

  /// A bus notification opens the tracking screen of the child who rides that bus.
  void _openFromNotification(AppNotification notification) {
    final children =
        ref.read(myTransportProvider).valueOrNull ?? const <ChildTransport>[];
    final onTrip =
        children.where((c) => c.vehicle != null && c.isOnTrip).toList();
    if (onTrip.isEmpty) return;
    final match = onTrip.firstWhere(
      (c) =>
          c.currentTripId == notification.tripId ||
          c.vehicle!.id == notification.vehicleId,
      orElse: () => onTrip.first,
    );
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => LiveTrackingScreen(child: match)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    ref.watch(notificationsLiveProvider);
    final unread = ref.watch(unreadCountProvider);
    final pages = [
      const ParentHomeScreen(),
      const ParentHistoryScreen(),
      NotificationsScreen(
          splitByKind: true, onOpenTransport: _openFromNotification),
      ProfileScreen(title: s.profile),
    ];
    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: [
          NavigationDestination(
              icon: const Icon(Icons.home_rounded), label: s.navHome),
          NavigationDestination(
              icon: const Icon(Icons.history_rounded), label: s.navHistory),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text('$unread'),
              child: const Icon(Icons.notifications_rounded),
            ),
            label: s.navNotifications,
          ),
          NavigationDestination(
              icon: const Icon(Icons.person_rounded), label: s.navProfile),
        ],
      ),
    );
  }
}

ChildTransport? _selected(List<ChildTransport> children, String? selectedId) {
  if (children.isEmpty) return null;
  return children.firstWhere((c) => c.studentId == selectedId,
      orElse: () => children.first);
}

/// Home: who, which bus, where it is now, which stop, what happened last.
class ParentHomeScreen extends ConsumerWidget {
  const ParentHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final transport = ref.watch(myTransportProvider);
    void refresh() {
      ref.invalidate(myTransportProvider);
      ref.invalidate(parentTripsProvider);
      ref.invalidate(notificationsProvider);
    }

    return Scaffold(
      appBar: AppBar(title: Text(s.myChildren)),
      body: AsyncBody<List<ChildTransport>>(
        value: transport,
        onRetry: refresh,
        builder: (children) {
          if (children.isEmpty) {
            return EmptyView(
                icon: Icons.child_care_rounded, message: s.noChildren);
          }
          final child = _selected(children, ref.watch(selectedChildProvider))!;
          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              children: [
                if (children.length > 1)
                  _ChildSelector(children: children, selected: child),
                const SizedBox(height: 8),
                _BusCard(child: child),
                if (child.hasAssignment) ...[
                  SectionTitle(s.todaysTrips),
                  _TodayTrips(child: child),
                ],
                SectionTitle(s.latestNotification),
                const _LatestNotification(),
                const _VideoEntry(),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ChildSelector extends ConsumerWidget {
  final List<ChildTransport> children;
  final ChildTransport selected;
  const _ChildSelector({required this.children, required this.selected});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: children.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final child = children[index];
          return ChoiceChip(
            label: Text(child.fullName),
            avatar: child.isOnTrip
                ? const Icon(Icons.circle, size: 10, color: RaadColors.green)
                : null,
            selected: child.studentId == selected.studentId,
            onSelected: (_) => ref.read(selectedChildProvider.notifier).state =
                child.studentId,
          );
        },
      ),
    );
  }
}

class _BusCard extends ConsumerWidget {
  final ChildTransport child;
  const _BusCard({required this.child});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    if (!child.hasAssignment) {
      return SectionCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(child.fullName,
                style:
                    const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            Text(s.noAssignment),
          ],
        ),
      );
    }
    final vehicle = child.vehicle;
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  child.fullName,
                  style: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.w800),
                ),
              ),
              StatusChip(
                label:
                    child.isOnTrip ? s.tripStatus('in_progress') : s.noTripNow,
                color: child.isOnTrip ? RaadColors.green : RaadColors.grey,
              ),
            ],
          ),
          const SizedBox(height: 8),
          InfoRow(
            icon: Icons.directions_bus_rounded,
            label: s.bus,
            value: vehicle?.displayName ?? s.noBusYet,
          ),
          if (child.routeName != null)
            InfoRow(
                icon: Icons.alt_route_rounded,
                label: s.route,
                value: child.routeName!),
          if (child.pickupStop != null)
            InfoRow(
              icon: Icons.location_on_rounded,
              label: s.pickupStop,
              value: child.pickupStop!.name,
            ),
          if (child.dropoffStop != null)
            InfoRow(
                icon: Icons.flag_rounded,
                label: s.dropoffStop,
                value: child.dropoffStop!.name),
          const SizedBox(height: 12),
          if (vehicle != null && child.isOnTrip)
            FilledButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                    builder: (_) => LiveTrackingScreen(child: child)),
              ),
              icon: const Icon(Icons.map_rounded),
              label: Text(s.trackBus),
            )
          else
            Text(s.trackingOnlyOnTrip,
                style: const TextStyle(color: RaadColors.grey)),
        ],
      ),
    );
  }
}

class _TodayTrips extends ConsumerWidget {
  final ChildTransport child;
  const _TodayTrips({required this.child});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final trips = ref.watch(parentTripsProvider);
    return trips.when(
      loading: () =>
          const SectionCard(child: SizedBox(height: 40, child: LoadingView())),
      error: (error, _) => SectionCard(child: Text(errorMessage(error, s))),
      data: (all) {
        final today = dateOnly(DateTime.now());
        final mine = all
            .where((t) =>
                t.scheduledDate == today &&
                t.studentIds.contains(child.studentId))
            .toList();
        if (mine.isEmpty) return SectionCard(child: Text(s.noTripsToday));
        return Column(
          children: [
            for (final trip in mine)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: TripTile(trip: trip),
              ),
          ],
        );
      },
    );
  }
}

/// One trip as a row: period, time, status, and the reason when it was cancelled.
class TripTile extends ConsumerWidget {
  final Trip trip;
  final bool showDate;
  final VoidCallback? onTap;
  const TripTile(
      {super.key, required this.trip, this.showDate = false, this.onTap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final time = shortTime(trip.plannedDeparture);
    final title = [
      if (showDate) friendlyDay(trip.scheduledDate, s),
      s.tripType(trip.tripType),
      if (time != null) time,
    ].join(' · ');
    return SectionCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                trip.tripType == 'morning'
                    ? Icons.wb_sunny_rounded
                    : Icons.wb_twilight_rounded,
                color: RaadColors.amber,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 15.5, fontWeight: FontWeight.w700)),
              ),
              if (trip.isCover) ...[
                StatusChip(label: s.coverBadge, color: RaadColors.amber),
                const SizedBox(width: 6),
              ],
              StatusChip(
                  label: s.tripStatus(trip.status),
                  color: tripStatusColor(trip.status)),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            [
              if (trip.routeName != null) trip.routeName!,
              if (trip.vehicle != null) trip.vehicle!.displayName,
            ].join(' · '),
            style: const TextStyle(color: RaadColors.grey),
          ),
          if (trip.isCancelled && trip.cancelledReason != null) ...[
            const SizedBox(height: 6),
            Text(
              '${s.cancelledReason}: ${trip.cancelledReason}',
              style: const TextStyle(
                  color: RaadColors.red, fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
    );
  }
}

class _LatestNotification extends ConsumerWidget {
  const _LatestNotification();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final list = ref.watch(notificationsProvider).valueOrNull;
    if (list == null) {
      return const SectionCard(
          child: SizedBox(height: 40, child: LoadingView()));
    }
    final transport = list.where((n) => n.isTransport).toList();
    if (transport.isEmpty) return SectionCard(child: Text(s.noNotifications));
    final n = transport.first;
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            s.notificationTitle(n.type, n.kind, n.title),
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5),
          ),
          const SizedBox(height: 4),
          Text(s.notificationBody(n.type, n.kind) ?? n.body),
          const SizedBox(height: 6),
          Text(
            friendlyMoment(n.createdAt, s),
            style: const TextStyle(fontSize: 12, color: RaadColors.grey),
          ),
        ],
      ),
    );
  }
}

/// Shown only to a parent the school has granted camera access (ADR-0026). The server checks
/// the grant again on every request; hiding the button is presentation, not security.
class _VideoEntry extends ConsumerWidget {
  const _VideoEntry();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final identity = ref.watch(myIdentityProvider).valueOrNull;
    if (identity == null || !identity.hasVideoLiveAccess) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: OutlinedButton.icon(
        style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => const VideoWatchScreen()),
        ),
        icon: const Icon(Icons.videocam_rounded),
        label: Text(s.watchVideo),
      ),
    );
  }
}

/// Trips of the children's bus, newest first. It says what RAAD knows (the trip ran, or was
/// cancelled and why) and is explicit that it does not know whether a child boarded.
class ParentHistoryScreen extends ConsumerWidget {
  const ParentHistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final children =
        ref.watch(myTransportProvider).valueOrNull ?? const <ChildTransport>[];
    final child = _selected(children, ref.watch(selectedChildProvider));
    final trips = ref.watch(parentTripsProvider);
    void refresh() => ref.invalidate(parentTripsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.historyTitle)),
      body: AsyncBody<List<Trip>>(
        value: trips,
        onRetry: refresh,
        builder: (all) {
          final today = dateOnly(DateTime.now());
          final past = all
              .where((t) =>
                  !t.scheduledDate.isAfter(today) &&
                  (child == null || t.studentIds.contains(child.studentId)))
              .toList()
              .reversed
              .toList();
          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (children.length > 1 && child != null) ...[
                  _ChildSelector(children: children, selected: child),
                  const SizedBox(height: 12),
                ],
                Text(s.historyNote,
                    style: const TextStyle(color: RaadColors.grey)),
                const SizedBox(height: 12),
                if (past.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 48),
                    child: EmptyView(
                        icon: Icons.history_rounded, message: s.noHistory),
                  ),
                for (final trip in past)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: TripTile(trip: trip, showDate: true),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}
