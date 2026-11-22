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
import 'parent_finance_screen.dart';

/// The Parent experience: Home (All Children & Buses), Finance, History, Notifications, Profile.
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
    final onTrip = children
        .where((c) => c.vehicle != null && c.isOnTrip)
        .toList();
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
      ParentHomeScreen(
        onOpenFinance: () => setState(() => _index = 1),
      ),
      const ParentFinanceScreen(),
      const ParentHistoryScreen(),
      NotificationsScreen(
        splitByKind: true,
        onOpenTransport: _openFromNotification,
      ),
      ProfileScreen(title: s.profile),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_rounded),
            label: s.navHome,
          ),
          NavigationDestination(
            icon: const Icon(Icons.account_balance_wallet_rounded),
            label: s.navFinance,
          ),
          NavigationDestination(
            icon: const Icon(Icons.history_rounded),
            label: s.navHistory,
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text('$unread'),
              child: const Icon(Icons.notifications_rounded),
            ),
            label: s.navNotifications,
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_rounded),
            label: s.navProfile,
          ),
        ],
      ),
    );
  }
}

/// Home: Unified multi-child view, bus tracking, absence reporting, finance summary, and today's trips.
class ParentHomeScreen extends ConsumerWidget {
  final VoidCallback? onOpenFinance;

  const ParentHomeScreen({super.key, this.onOpenFinance});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final transport = ref.watch(myTransportProvider);

    void refresh() {
      ref.invalidate(myTransportProvider);
      ref.invalidate(parentTripsProvider);
      ref.invalidate(parentInvoicesProvider);
      ref.invalidate(notificationsProvider);
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(s.myChildren),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Cusbooneysii',
            onPressed: refresh,
          ),
        ],
      ),
      body: AsyncBody<List<ChildTransport>>(
        value: transport,
        onRetry: refresh,
        builder: (children) {
          if (children.isEmpty) {
            return RefreshIndicator(
              onRefresh: () async => refresh(),
              child: ListView(
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: EmptyView(
                      icon: Icons.child_care_rounded,
                      message: s.noChildren,
                    ),
                  ),
                ],
              ),
            );
          }

          final onTripChildren =
              children.where((c) => c.vehicle != null && c.isOnTrip).toList();

          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
              children: [
                // Top Banner if any child is actively on a trip
                if (onTripChildren.isNotEmpty) ...[
                  _LiveBusAlertBanner(onTripChildren: onTripChildren),
                  const SizedBox(height: 12),
                ],

                // Multi-Child Header
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Dhamaan Carruurta (${children.length})',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      'Hal meel kaga wada socda',
                      style: TextStyle(fontSize: 12, color: context.muted),
                    ),
                  ],
                ),
                const SizedBox(height: 8),

                // Render every child in a unified card
                for (final child in children) ...[
                  _UnifiedChildCard(child: child),
                  const SizedBox(height: 12),
                ],

                const SizedBox(height: 8),

                // Quick Finance Summary Card
                _ParentFinanceQuickCard(onTap: onOpenFinance),
                const SizedBox(height: 16),

                // Today's trips across all children
                SectionTitle(s.todaysTrips),
                _UnifiedTodayTrips(children: children),
                const SizedBox(height: 16),

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

class _LiveBusAlertBanner extends StatelessWidget {
  final List<ChildTransport> onTripChildren;

  const _LiveBusAlertBanner({required this.onTripChildren});

  @override
  Widget build(BuildContext context) {
    final first = onTripChildren.first;
    final busName = first.vehicle?.displayName ?? 'Baska';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: RaadColors.green.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: RaadColors.green.withValues(alpha: 0.5)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: const BoxDecoration(
              color: RaadColors.green,
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.directions_bus_rounded,
              color: Colors.white,
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$busName wuu socdaa hadda!',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 14.5,
                    color: RaadColors.green,
                  ),
                ),
                Text(
                  onTripChildren.length == 1
                      ? '${first.fullName} ayaa baska ku jira.'
                      : '${onTripChildren.map((c) => c.fullName).join(", ")} ayaa baska ku jira.',
                  style: TextStyle(fontSize: 12, color: context.muted),
                ),
              ],
            ),
          ),
          FilledButton.tonal(
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            ),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => LiveTrackingScreen(child: first),
              ),
            ),
            child: const Text('Toos u eeg', style: TextStyle(fontSize: 12.5)),
          ),
        ],
      ),
    );
  }
}

/// Unified Child Card: Full details for each child, tracking button, absence reporting
class _UnifiedChildCard extends ConsumerWidget {
  final ChildTransport child;

  const _UnifiedChildCard({required this.child});

  void _openAbsenceDialog(BuildContext context, WidgetRef ref) {
    final s = ref.read(stringsProvider);
    final reasonController = TextEditingController();
    bool isSubmitting = false;

    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 20,
                bottom: MediaQuery.of(context).viewInsets.bottom + 24,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: RaadColors.amber.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: const Icon(
                          Icons.do_not_disturb_on_rounded,
                          color: RaadColors.amber,
                          size: 24,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'Yaa la soo marin: ${child.fullName}',
                          style: const TextStyle(
                            fontSize: 16.5,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Marka aad maqnaansho diiwaangeliso, darwalka baska waxaa si toos ah loogu sheegi doonaa inuu dhaafo joogsiga ilmahaaga maanta oo uusan soo marin xaafadda.',
                    style: TextStyle(fontSize: 13, color: context.muted),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: reasonController,
                    decoration: InputDecoration(
                      labelText: s.absenceReasonHint,
                      hintText: 'Tusaale: Xanuun, Fasax qoys, iwm.',
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      prefixIcon: const Icon(Icons.edit_note_rounded),
                    ),
                  ),
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: isSubmitting
                              ? null
                              : () => Navigator.of(context).pop(),
                          child: const Text('Ka noqo'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: RaadColors.red,
                          ),
                          onPressed: isSubmitting
                              ? null
                              : () async {
                                  setModalState(() => isSubmitting = true);
                                  try {
                                    final note = reasonController.text.trim();
                                    await ref
                                        .read(repositoryProvider)
                                        .reportStudentAbsence(
                                          child.studentId,
                                          notes: note.isEmpty
                                              ? 'Waalidka: Yaa la soo marin maanta'
                                              : note,
                                        );
                                    if (context.mounted) {
                                      Navigator.of(context).pop();
                                      showNotice(
                                        context,
                                        'Maqnaanshaha waa la diiwaangeliyay. Darwalka waa la ogeysiiyay inuusan soo marin.',
                                      );
                                      ref.invalidate(myTransportProvider);
                                      ref.invalidate(parentTripsProvider);
                                    }
                                  } catch (e) {
                                    setModalState(() => isSubmitting = false);
                                    if (context.mounted) {
                                      showNotice(
                                        context,
                                        'Khalad ayaa dhacay: $e',
                                        isError: true,
                                      );
                                    }
                                  }
                                },
                          child: isSubmitting
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Text('Xaqiiji Maqnaanshaha'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final vehicle = child.vehicle;
    final initialLetter =
        child.fullName.isNotEmpty ? child.fullName[0].toUpperCase() : 'A';

    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Child Header Row
          Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: child.isOnTrip
                    ? RaadColors.green.withValues(alpha: 0.15)
                    : Theme.of(context).colorScheme.primaryContainer,
                child: Text(
                  initialLetter,
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                    color: child.isOnTrip
                        ? RaadColors.green
                        : Theme.of(context).colorScheme.primary,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      child.fullName,
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    Text(
                      child.hasAssignment
                          ? (child.routeName ?? 'Khad loo qoondeeyay')
                          : s.noAssignment,
                      style: TextStyle(fontSize: 12, color: context.muted),
                    ),
                  ],
                ),
              ),
              StatusChip(
                label: child.isOnTrip
                    ? s.tripStatus('in_progress')
                    : (child.hasAssignment ? 'Diyaar' : 'Bas la\'aan'),
                color: child.isOnTrip
                    ? RaadColors.green
                    : (child.hasAssignment ? RaadColors.primary : RaadColors.grey),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Transport info if assigned
          if (child.hasAssignment) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: Theme.of(context)
                    .colorScheme
                    .surfaceContainerHighest
                    .withValues(alpha: 0.35),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Icon(Icons.directions_bus_rounded,
                          size: 18, color: RaadColors.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          vehicle?.displayName ?? s.noBusYet,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (child.pickupStop != null || child.dropoffStop != null) ...[
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        const Icon(Icons.location_on_rounded,
                            size: 18, color: RaadColors.grey),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            [
                              if (child.pickupStop != null)
                                'Qaadashada: ${child.pickupStop!.name}',
                              if (child.dropoffStop != null)
                                'Dejinta: ${child.dropoffStop!.name}',
                            ].join(' · '),
                            style: TextStyle(
                              fontSize: 12,
                              color: context.muted,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Actions row
          Row(
            children: [
              if (vehicle != null && child.isOnTrip) ...[
                Expanded(
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => LiveTrackingScreen(child: child),
                      ),
                    ),
                    icon: const Icon(Icons.map_rounded, size: 18),
                    label: Text(s.trackBus),
                  ),
                ),
                const SizedBox(width: 8),
              ],
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    foregroundColor: RaadColors.red,
                    side: BorderSide(
                      color: RaadColors.red.withValues(alpha: 0.4),
                    ),
                  ),
                  onPressed: () => _openAbsenceDialog(context, ref),
                  icon: const Icon(Icons.do_not_disturb_on_rounded, size: 18),
                  label: const Text(
                    'Yaa la soo marin',
                    style: TextStyle(fontSize: 12.5),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ParentFinanceQuickCard extends ConsumerWidget {
  final VoidCallback? onTap;

  const _ParentFinanceQuickCard({this.onTap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final finance = ref.watch(parentInvoicesProvider).valueOrNull;
    final hasBalance = finance?.hasOutstanding == true;
    final balance = finance?.balanceDue ?? '0.00';

    return SectionCard(
      onTap: onTap,
      child: Row(
        children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: hasBalance
                ? RaadColors.amber.withValues(alpha: 0.15)
                : RaadColors.green.withValues(alpha: 0.15),
            child: Icon(
              hasBalance
                  ? Icons.account_balance_wallet_rounded
                  : Icons.check_circle_rounded,
              color: hasBalance ? RaadColors.amber : RaadColors.green,
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Biilasha & Lacagaha Bisha',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                ),
                Text(
                  hasBalance
                      ? 'Lacag dhiman: \$$balance'
                      : 'Dhammaan biilasha waa la bixiyay',
                  style: TextStyle(
                    fontSize: 12,
                    color: hasBalance ? RaadColors.red : RaadColors.green,
                  ),
                ),
              ],
            ),
          ),
          Icon(Icons.chevron_right_rounded, color: context.muted),
        ],
      ),
    );
  }
}

/// Unified Today's Trips for all children
class _UnifiedTodayTrips extends ConsumerWidget {
  final List<ChildTransport> children;

  const _UnifiedTodayTrips({required this.children});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final trips = ref.watch(parentTripsProvider);
    final studentIds = children.map((c) => c.studentId).toSet();

    return trips.when(
      loading: () =>
          const SectionCard(child: SizedBox(height: 40, child: LoadingView())),
      error: (error, _) => SectionCard(child: Text(errorMessage(error, s))),
      data: (all) {
        final today = dateOnly(DateTime.now());
        final todayTrips = all
            .where(
              (t) =>
                  t.scheduledDate == today &&
                  t.studentIds.any((id) => studentIds.contains(id)),
            )
            .toList();

        if (todayTrips.isEmpty) {
          return SectionCard(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(s.noTripsToday, style: TextStyle(color: context.muted)),
            ),
          );
        }

        return Column(
          children: [
            for (final trip in todayTrips)
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
  const TripTile({
    super.key,
    required this.trip,
    this.showDate = false,
    this.onTap,
  });

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
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 15.5,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              if (trip.isCover) ...[
                StatusChip(label: s.coverBadge, color: RaadColors.amber),
                const SizedBox(width: 6),
              ],
              StatusChip(
                label: s.tripStatus(trip.status),
                color: tripStatusColor(trip.status),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            [
              if (trip.routeName != null) trip.routeName!,
              if (trip.vehicle != null) trip.vehicle!.displayName,
            ].join(' · '),
            style: TextStyle(color: context.muted),
          ),
          if (trip.isCancelled && trip.cancelledReason != null) ...[
            const SizedBox(height: 6),
            Text(
              '${s.cancelledReason}: ${trip.cancelledReason}',
              style: const TextStyle(
                color: RaadColors.red,
                fontWeight: FontWeight.w600,
              ),
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
        child: SizedBox(height: 40, child: LoadingView()),
      );
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
            style: TextStyle(fontSize: 12, color: context.muted),
          ),
        ],
      ),
    );
  }
}

/// Shown only to a parent the school has granted camera access (ADR-0026).
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

/// Trips of the children's buses, newest first.
class ParentHistoryScreen extends ConsumerWidget {
  const ParentHistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final children =
        ref.watch(myTransportProvider).valueOrNull ?? const <ChildTransport>[];
    final trips = ref.watch(parentTripsProvider);
    void refresh() => ref.invalidate(parentTripsProvider);

    return Scaffold(
      appBar: AppBar(title: Text(s.historyTitle)),
      body: AsyncBody<List<Trip>>(
        value: trips,
        onRetry: refresh,
        builder: (all) {
          final today = dateOnly(DateTime.now());
          final studentIds = children.map((c) => c.studentId).toSet();
          final past = all
              .where(
                (t) =>
                    !t.scheduledDate.isAfter(today) &&
                    (studentIds.isEmpty ||
                        t.studentIds.any((id) => studentIds.contains(id))),
              )
              .toList()
              .reversed
              .toList();

          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(s.historyNote, style: TextStyle(color: context.muted)),
                const SizedBox(height: 12),
                if (past.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 48),
                    child: EmptyView(
                      icon: Icons.history_rounded,
                      message: s.noHistory,
                    ),
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
