import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../common/notifications_screen.dart';
import '../common/profile_screen.dart';
import '../parent/parent_screens.dart' show TripTile;
import 'driver_self_service.dart';

/// The Driver experience: Today, Trips, Notifications, More.
///
/// The app is a control surface. It never reads the phone's location: the bus's own terminal
/// is the tracking source (`.claude/rules/flutter.md` #2).
class DriverShell extends ConsumerStatefulWidget {
  const DriverShell({super.key});

  @override
  ConsumerState<DriverShell> createState() => _DriverShellState();
}

class _DriverShellState extends ConsumerState<DriverShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    ref.watch(notificationsLiveProvider);
    final unread = ref.watch(unreadCountProvider);
    final pages = [
      const DriverTodayScreen(),
      const DriverTripsScreen(),
      const NotificationsScreen(splitByKind: false),
      const DriverMoreScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: [
          NavigationDestination(
              icon: const Icon(Icons.today_rounded), label: s.navToday),
          NavigationDestination(
              icon: const Icon(Icons.route_rounded), label: s.navTrips),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text('$unread'),
              child: const Icon(Icons.notifications_rounded),
            ),
            label: s.navNotifications,
          ),
          NavigationDestination(
              icon: const Icon(Icons.menu_rounded), label: s.navMore),
        ],
      ),
    );
  }
}

void _openTrip(BuildContext context, Trip trip) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(builder: (_) => TripDetailScreen(tripId: trip.id)),
  );
}

/// Today's trips, with the one action that matters on each: start it, or end it.
class DriverTodayScreen extends ConsumerWidget {
  const DriverTodayScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final trips = ref.watch(driverTripsProvider);
    void refresh() => ref.invalidate(driverTripsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.navToday)),
      body: AsyncBody<List<Trip>>(
        value: trips,
        onRetry: refresh,
        builder: (all) {
          final today = dateOnly(DateTime.now());
          final mine = all.where((t) => t.scheduledDate == today).toList();
          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (mine.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: EmptyView(
                        icon: Icons.event_available_rounded,
                        message: s.noTripsToday),
                  ),
                for (final trip in mine)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TripTile(
                            trip: trip, onTap: () => _openTrip(context, trip)),
                        if (trip.isScheduled || trip.isInProgress) ...[
                          const SizedBox(height: 8),
                          TripActionButton(trip: trip),
                        ],
                      ],
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Start or end a trip. The server decides whether this driver may: another driver's trip is
/// refused there, whatever this screen shows.
class TripActionButton extends ConsumerStatefulWidget {
  final Trip trip;
  const TripActionButton({super.key, required this.trip});

  @override
  ConsumerState<TripActionButton> createState() => _TripActionButtonState();
}

class _TripActionButtonState extends ConsumerState<TripActionButton> {
  bool _busy = false;

  Future<void> _act() async {
    final s = ref.read(stringsProvider);
    final starting = widget.trip.isScheduled;
    final ok = await confirm(
      context,
      title: starting ? s.startTripConfirm : s.endTripConfirm,
      s: s,
    );
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    try {
      final repository = ref.read(repositoryProvider);
      await (starting
          ? repository.startTrip(widget.trip.id)
          : repository.endTrip(widget.trip.id));
    } catch (error) {
      if (mounted) showError(context, error, s);
    } finally {
      ref.invalidate(driverTripsProvider);
      ref.invalidate(tripDetailProvider(widget.trip.id));
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final starting = widget.trip.isScheduled;
    return FilledButton.icon(
      style: FilledButton.styleFrom(
        backgroundColor: starting ? RaadColors.green : RaadColors.red,
      ),
      onPressed: _busy ? null : _act,
      icon: _busy
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Colors.white),
            )
          : Icon(starting ? Icons.play_arrow_rounded : Icons.stop_rounded),
      label: Text(starting ? s.startTrip : s.endTrip),
    );
  }
}

/// Upcoming and past trips.
class DriverTripsScreen extends ConsumerWidget {
  const DriverTripsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final trips = ref.watch(driverTripsProvider);
    void refresh() => ref.invalidate(driverTripsProvider);

    Widget list(List<Trip> items) {
      if (items.isEmpty)
        return EmptyView(icon: Icons.route_rounded, message: s.noHistory);
      return RefreshIndicator(
        onRefresh: () async => refresh(),
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: items.length,
          separatorBuilder: (_, __) => const SizedBox(height: 8),
          itemBuilder: (context, index) => TripTile(
            trip: items[index],
            showDate: true,
            onTap: () => _openTrip(context, items[index]),
          ),
        ),
      );
    }

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(s.myTrips),
          bottom: TabBar(tabs: [Tab(text: s.upcoming), Tab(text: s.past)]),
        ),
        body: AsyncBody<List<Trip>>(
          value: trips,
          onRetry: refresh,
          builder: (all) {
            final today = dateOnly(DateTime.now());
            final upcoming = all
                .where((t) => !t.scheduledDate.isBefore(today) && !t.isFinished)
                .toList();
            final past = all
                .where((t) => t.scheduledDate.isBefore(today) || t.isFinished)
                .toList()
                .reversed
                .toList();
            return TabBarView(children: [list(upcoming), list(past)]);
          },
        ),
      ),
    );
  }
}

/// One of the driver's own trips: status, bus, route, the stops in order, who is on the crew
/// and which students ride.
class TripDetailScreen extends ConsumerWidget {
  final String tripId;
  const TripDetailScreen({super.key, required this.tripId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final detail = ref.watch(tripDetailProvider(tripId));
    void refresh() => ref.invalidate(tripDetailProvider(tripId));
    return Scaffold(
      appBar: AppBar(title: Text(s.tripDetails)),
      body: AsyncBody<TripDetail>(
        value: detail,
        onRetry: refresh,
        builder: (d) {
          final trip = d.trip;
          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                TripTile(trip: trip, showDate: true),
                if (trip.isCover) ...[
                  const SizedBox(height: 8),
                  Text(s.coverNote,
                      style: const TextStyle(color: RaadColors.amber)),
                ],
                if (trip.isScheduled || trip.isInProgress) ...[
                  const SizedBox(height: 12),
                  TripActionButton(trip: trip),
                ],
                SectionTitle('${s.stops} (${d.stops.length})'),
                SectionCard(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Column(
                    children: [
                      for (final stop in d.stops)
                        ListTile(
                          dense: true,
                          leading: CircleAvatar(
                            radius: 14,
                            child: Text('${stop.sequenceNo ?? ''}',
                                style: const TextStyle(fontSize: 12)),
                          ),
                          title: Text(stop.name),
                        ),
                    ],
                  ),
                ),
                SectionTitle('${s.passengers} (${d.passengers.length})'),
                if (d.passengers.isEmpty)
                  SectionCard(child: Text(s.noPassengers))
                else
                  SectionCard(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Column(
                      children: [
                        for (final p in d.passengers)
                          ListTile(
                            dense: true,
                            leading: const Icon(Icons.person_rounded),
                            title: Text(p.fullName),
                            subtitle: Text(
                              [
                                if (p.pickupStopName != null) p.pickupStopName!,
                                if (p.dropoffStopName != null)
                                  p.dropoffStopName!,
                              ].join(' → '),
                            ),
                          ),
                      ],
                    ),
                  ),
                SectionTitle(s.crew),
                CrewList(members: d.crew),
              ],
            ),
          );
        },
      ),
    );
  }
}

class CrewList extends ConsumerWidget {
  final List<CrewMember> members;
  const CrewList({super.key, required this.members});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    if (members.isEmpty) return SectionCard(child: Text(s.noCrew));
    return SectionCard(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        children: [
          for (final m in members)
            ListTile(
              dense: true,
              leading: const Icon(Icons.badge_rounded),
              title: Text(m.isMe ? '${m.fullName} (${s.you})' : m.fullName),
              subtitle: m.roleName == null ? null : Text(m.roleName!),
              trailing: m.isSubstitute
                  ? StatusChip(label: s.substitute, color: RaadColors.amber)
                  : null,
            ),
        ],
      ),
    );
  }
}

/// The driver's account and self-service: crew, documents, days off, incident reports.
class DriverMoreScreen extends ConsumerWidget {
  const DriverMoreScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    Widget entry(IconData icon, String label, Widget Function() page) {
      return Padding(
        padding: const EdgeInsets.only(top: 8),
        child: SectionCard(
          padding: EdgeInsets.zero,
          child: ListTile(
            leading: Icon(icon, color: RaadColors.blue),
            title: Text(label,
                style: const TextStyle(fontWeight: FontWeight.w600)),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => page()),
            ),
          ),
        ),
      );
    }

    return ProfileScreen(
      title: s.navMore,
      extra: [
        const SizedBox(height: 8),
        entry(Icons.groups_rounded, s.crew, () => const CrewScreen()),
        entry(Icons.description_rounded, s.documents,
            () => const DocumentsScreen()),
        entry(Icons.event_busy_rounded, s.unavailability,
            () => const UnavailabilityScreen()),
        entry(Icons.report_rounded, s.incidents, () => const IncidentsScreen()),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 12, 4, 0),
          child: Text(s.gpsFromBus,
              style: const TextStyle(fontSize: 12.5, color: RaadColors.grey)),
        ),
      ],
    );
  }
}
