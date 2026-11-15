import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

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
            icon: const Icon(Icons.today_rounded),
            label: s.navToday,
          ),
          NavigationDestination(
            icon: const Icon(Icons.route_rounded),
            label: s.navTrips,
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
            icon: const Icon(Icons.menu_rounded),
            label: s.navMore,
          ),
        ],
      ),
    );
  }
}

void _openAssignStudentStopModal(
  BuildContext context, [
  String? preselectedRouteId,
  String? preselectedVehicleId,
]) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) => _AssignStudentStopSheet(
      initialRouteId: preselectedRouteId,
      initialVehicleId: preselectedVehicleId,
    ),
  );
}

void _openTrip(BuildContext context, Trip trip) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(builder: (_) => TripDetailScreen(tripId: trip.id)),
  );
}

void _openTripAttendance(BuildContext context, Trip trip) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => DriverTripAttendanceScreen(trip: trip),
    ),
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
    final allTrips = trips.valueOrNull ?? const <Trip>[];
    final today = dateOnly(DateTime.now());
    final mine = allTrips.where((t) => t.scheduledDate == today).toList();

    return Scaffold(
      appBar: AppBar(
        title: Text(s.navToday),
        actions: [
          IconButton(
            icon: const Icon(Icons.fact_check_rounded),
            tooltip: s.attendanceTitle,
            onPressed: () {
              if (mine.isNotEmpty) {
                final active = mine.firstWhere(
                  (t) => t.isInProgress,
                  orElse: () => mine.first,
                );
                _openTripAttendance(context, active);
              } else {
                showNotice(context, s.noTripsToday);
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.add_location_alt_rounded),
            tooltip: s.assignStudentStop,
            onPressed: () {
              final active = trips.valueOrNull?.where((t) => t.status == 'in_progress').firstOrNull;
              final first = trips.valueOrNull?.firstOrNull;
              _openAssignStudentStopModal(
                context,
                active?.routeId ?? first?.routeId,
                active?.vehicle?.id ?? first?.vehicle?.id,
              );
            },
          ),
        ],
      ),
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
                      message: s.noTripsToday,
                    ),
                  ),
                for (final trip in mine)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TripTile(
                          trip: trip,
                          onTap: () => _openTrip(context, trip),
                        ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            if (trip.isScheduled || trip.isInProgress) ...[
                              Expanded(
                                flex: 3,
                                child: TripActionButton(trip: trip),
                              ),
                              const SizedBox(width: 8),
                            ],
                            Expanded(
                              flex: 2,
                              child: OutlinedButton.icon(
                                style: OutlinedButton.styleFrom(
                                  padding: const EdgeInsets.symmetric(vertical: 12),
                                  foregroundColor: RaadColors.green,
                                  side: BorderSide(
                                    color: RaadColors.green.withValues(alpha: 0.5),
                                  ),
                                ),
                                icon: const Icon(Icons.fact_check_rounded, size: 18),
                                label: Text(s.attendance),
                                onPressed: () => _openTripAttendance(context, trip),
                              ),
                            ),
                          ],
                        ),
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
                strokeWidth: 2,
                color: Colors.white,
              ),
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
      if (items.isEmpty) {
        return EmptyView(icon: Icons.route_rounded, message: s.noHistory);
      }
      return RefreshIndicator(
        onRefresh: () async => refresh(),
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: items.length,
          separatorBuilder: (_, __) => const SizedBox(height: 12),
          itemBuilder: (context, index) {
            final t = items[index];
            return Card(
              margin: EdgeInsets.zero,
              clipBehavior: Clip.antiAlias,
              child: Column(
                children: [
                  TripTile(
                    trip: t,
                    showDate: true,
                    onTap: () => _openTrip(context, t),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton.icon(
                          icon: const Icon(Icons.fact_check_rounded, size: 16),
                          label: Text(s.attendanceTitle, style: const TextStyle(fontSize: 12)),
                          onPressed: () => _openTripAttendance(context, t),
                        ),
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

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(s.myTrips),
          bottom: TabBar(
            tabs: [
              Tab(text: s.upcoming),
              Tab(text: s.past),
            ],
          ),
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
                  Text(
                    s.coverNote,
                    style: const TextStyle(color: RaadColors.amber),
                  ),
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
                            child: Text(
                              '${stop.sequenceNo ?? ''}',
                              style: const TextStyle(fontSize: 12),
                            ),
                          ),
                          title: Text(stop.name),
                        ),
                    ],
                  ),
                ),
                _TripPassengersAttendanceSection(trip: trip, passengers: d.passengers),
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
            title: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () =>
                Navigator.of(context)
                    .push(MaterialPageRoute<void>(builder: (_) => page())),
          ),
        ),
      );
    }

    return ProfileScreen(
      title: s.navMore,
      extra: [
        const SizedBox(height: 8),
        entry(Icons.groups_rounded, s.crew, () => const CrewScreen()),
        entry(
          Icons.description_rounded,
          s.documents,
          () => const DocumentsScreen(),
        ),
        entry(
          Icons.event_busy_rounded,
          s.unavailability,
          () => const UnavailabilityScreen(),
        ),
        entry(Icons.report_rounded, s.incidents, () => const IncidentsScreen()),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 12, 4, 0),
          child: Text(
            s.gpsFromBus,
            style: TextStyle(fontSize: 12.5, color: context.muted),
          ),
        ),
      ],
    );
  }
}

class _TripPassengersAttendanceSection extends ConsumerStatefulWidget {
  final Trip trip;
  final List<Passenger> passengers;

  const _TripPassengersAttendanceSection({
    required this.trip,
    required this.passengers,
  });

  @override
  ConsumerState<_TripPassengersAttendanceSection> createState() =>
      _TripPassengersAttendanceSectionState();
}

class _TripPassengersAttendanceSectionState
    extends ConsumerState<_TripPassengersAttendanceSection> {
  final Set<String> _pendingToggles = {};

  Future<void> _toggleAttendance(Passenger passenger, bool isCurrentlyPresent) async {
    final s = ref.read(stringsProvider);
    final studentId = passenger.studentId;
    if (studentId.isEmpty || _pendingToggles.contains(studentId)) return;

    setState(() => _pendingToggles.add(studentId));
    final newStatus = isCurrentlyPresent ? 'absent' : 'present';
    try {
      await ref.read(repositoryProvider).recordAttendance(
            tripId: widget.trip.id,
            studentId: studentId,
            status: newStatus,
          );
      ref.invalidate(tripAttendanceProvider(widget.trip.id));
      if (mounted) {
        showNotice(
          context,
          newStatus == 'present'
              ? '${passenger.fullName} - ${s.markPresent}'
              : '${passenger.fullName} - ${s.markAbsent}',
        );
      }
    } catch (err) {
      if (mounted) showError(context, err, s);
    } finally {
      if (mounted) setState(() => _pendingToggles.remove(studentId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final attendanceAsync = ref.watch(tripAttendanceProvider(widget.trip.id));
    final records = attendanceAsync.valueOrNull ?? const <AttendanceRecord>[];
    final attendanceMap = {for (final a in records) a.studentId: a};

    final presentCount = widget.passengers
        .where((p) => attendanceMap[p.studentId]?.isPresent == true)
        .length;
    final totalCount = widget.passengers.length;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: SectionTitle(
                '${s.attendanceTitle} ($presentCount/$totalCount)',
              ),
            ),
            TextButton.icon(
              icon: const Icon(Icons.add_location_alt_outlined, size: 16),
              label: Text(s.assignStudentStop, style: const TextStyle(fontSize: 12)),
              onPressed: () => _openAssignStudentStopModal(
                context,
                widget.trip.routeId,
                widget.trip.vehicle?.id,
              ),
            ),
          ],
        ),
        if (widget.passengers.isEmpty)
          SectionCard(child: Text(s.noPassengers))
        else
          SectionCard(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Column(
              children: [
                if (totalCount > 0)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              '${s.attendanceStats}: $presentCount ${s.present.toLowerCase()}',
                              style: const TextStyle(
                                fontSize: 12.5,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            Text(
                              '${(presentCount / totalCount * 100).toInt()}%',
                              style: TextStyle(
                                fontSize: 12.5,
                                fontWeight: FontWeight.bold,
                                color: presentCount > 0 ? RaadColors.green : context.muted,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: LinearProgressIndicator(
                            value: totalCount > 0 ? presentCount / totalCount : 0,
                            minHeight: 6,
                            backgroundColor: Theme.of(context).colorScheme.surfaceContainerHighest,
                            valueColor: const AlwaysStoppedAnimation(RaadColors.green),
                          ),
                        ),
                      ],
                    ),
                  ),
                for (final p in widget.passengers) ...[
                  _PassengerAttendanceTile(
                    passenger: p,
                    record: attendanceMap[p.studentId],
                    isPending: _pendingToggles.contains(p.studentId),
                    onToggle: () {
                      final isPresent = attendanceMap[p.studentId]?.isPresent == true;
                      _toggleAttendance(p, isPresent);
                    },
                  ),
                  if (p != widget.passengers.last)
                    const Divider(height: 1, indent: 56),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

class _PassengerAttendanceTile extends StatelessWidget {
  final Passenger passenger;
  final AttendanceRecord? record;
  final bool isPending;
  final VoidCallback onToggle;

  const _PassengerAttendanceTile({
    required this.passenger,
    required this.record,
    required this.isPending,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    final isPresent = record?.isPresent == true;

    return ListTile(
      dense: true,
      leading: CircleAvatar(
        radius: 17,
        backgroundColor: isPresent
            ? RaadColors.green.withValues(alpha: 0.15)
            : context.muted.withValues(alpha: 0.12),
        child: Icon(
          Icons.person_rounded,
          size: 19,
          color: isPresent ? RaadColors.green : context.muted,
        ),
      ),
      title: Text(
        passenger.fullName,
        style: TextStyle(
          fontWeight: isPresent ? FontWeight.bold : FontWeight.w600,
          fontSize: 14,
        ),
      ),
      subtitle: Text(
        (passenger.pickupStopName != null || passenger.dropoffStopName != null)
            ? [
                if (passenger.pickupStopName != null) passenger.pickupStopName!,
                if (passenger.dropoffStopName != null) passenger.dropoffStopName!,
              ].join(' → ')
            : 'Weli ma laha joogsi cayiman',
        style: TextStyle(fontSize: 12, color: context.muted),
      ),
      trailing: InkWell(
        onTap: isPending ? null : onToggle,
        borderRadius: BorderRadius.circular(20),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: isPresent
                ? RaadColors.green.withValues(alpha: 0.15)
                : Theme.of(context).colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: isPresent
                  ? RaadColors.green
                  : Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.5),
              width: 1.2,
            ),
          ),
          child: isPending
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      isPresent
                          ? Icons.check_circle_rounded
                          : Icons.radio_button_unchecked_rounded,
                      size: 18,
                      color: isPresent ? RaadColors.green : context.muted,
                    ),
                    const SizedBox(width: 5),
                    Text(
                      isPresent ? s.markPresent : s.markAbsent,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: isPresent ? RaadColors.green : context.muted,
                      ),
                    ),
                  ],
                ),
        ),
      ),
    );
  }
}

class DriverTripAttendanceScreen extends ConsumerStatefulWidget {
  final Trip trip;
  const DriverTripAttendanceScreen({super.key, required this.trip});

  @override
  ConsumerState<DriverTripAttendanceScreen> createState() =>
      _DriverTripAttendanceScreenState();
}

class _DriverTripAttendanceScreenState
    extends ConsumerState<DriverTripAttendanceScreen> {
  final Set<String> _pendingToggles = {};
  String _filter = 'all'; // 'all', 'present', 'absent'

  Future<void> _toggleAttendance(Passenger passenger, bool isCurrentlyPresent) async {
    final s = ref.read(stringsProvider);
    final nextStatus = isCurrentlyPresent ? 'absent' : 'present';
    setState(() => _pendingToggles.add(passenger.studentId));

    try {
      await ref.read(repositoryProvider).recordAttendance(
            tripId: widget.trip.id,
            studentId: passenger.studentId,
            status: nextStatus,
          );
      ref.invalidate(tripAttendanceProvider(widget.trip.id));
      if (mounted) {
        showNotice(
          context,
          nextStatus == 'present'
              ? '${passenger.fullName} - ${s.present}'
              : '${passenger.fullName} - ${s.absent}',
        );
      }
    } catch (e) {
      if (mounted) showError(context, e, s);
    } finally {
      if (mounted) setState(() => _pendingToggles.remove(passenger.studentId));
    }
  }

  Future<void> _markAllPresent(
    List<Passenger> passengers,
    Map<String, AttendanceRecord> attendanceMap,
  ) async {
    final s = ref.read(stringsProvider);
    final unpresent = passengers
        .where((p) => attendanceMap[p.studentId]?.isPresent != true)
        .toList();
    if (unpresent.isEmpty) {
      showNotice(context, s.allStudents);
      return;
    }
    final ok = await confirm(
      context,
      title: s.markAllPresentConfirm,
      s: s,
    );
    if (!ok || !mounted) return;

    for (final p in unpresent) {
      try {
        await ref.read(repositoryProvider).recordAttendance(
              tripId: widget.trip.id,
              studentId: p.studentId,
              status: 'present',
            );
      } catch (_) {}
    }
    ref.invalidate(tripAttendanceProvider(widget.trip.id));
    if (mounted) {
      showNotice(context, s.attendanceSaved);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final detailAsync = ref.watch(tripDetailProvider(widget.trip.id));
    final attendanceAsync = ref.watch(tripAttendanceProvider(widget.trip.id));

    void refresh() {
      ref.invalidate(tripDetailProvider(widget.trip.id));
      ref.invalidate(tripAttendanceProvider(widget.trip.id));
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(s.attendanceTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_location_alt_rounded),
            tooltip: s.assignStudentStop,
            onPressed: () => _openAssignStudentStopModal(
              context,
              widget.trip.routeId,
              widget.trip.vehicle?.id,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: s.retry,
            onPressed: refresh,
          ),
        ],
      ),
      body: AsyncBody<TripDetail>(
        value: detailAsync,
        onRetry: refresh,
        builder: (detail) {
          final passengers = detail.passengers;
          final records = attendanceAsync.valueOrNull ?? const <AttendanceRecord>[];
          final attendanceMap = {for (final a in records) a.studentId: a};

          final presentCount = passengers
              .where((p) => attendanceMap[p.studentId]?.isPresent == true)
              .length;
          final totalCount = passengers.length;
          final absentCount = totalCount - presentCount;
          final rate = totalCount > 0 ? (presentCount / totalCount * 100).toInt() : 0;

          final filteredPassengers = passengers.where((p) {
            final isPresent = attendanceMap[p.studentId]?.isPresent == true;
            if (_filter == 'present') return isPresent;
            if (_filter == 'absent') return !isPresent;
            return true;
          }).toList();

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Trip Info Banner
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: RaadColors.primary.withValues(alpha: 0.15),
                      child: const Icon(Icons.directions_bus_rounded, color: RaadColors.primary),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            detail.trip.routeName ?? 'Khadka Safarka',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${detail.trip.tripType.toUpperCase()} · ${isoDate(detail.trip.scheduledDate)}',
                            style: TextStyle(fontSize: 12, color: context.muted),
                          ),
                        ],
                      ),
                    ),
                    if (totalCount > 0)
                      TextButton.icon(
                        icon: const Icon(Icons.done_all_rounded, size: 16),
                        label: Text(s.markAllPresent, style: const TextStyle(fontSize: 12)),
                        onPressed: () => _markAllPresent(passengers, attendanceMap),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              // KPI Progress Card
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Theme.of(context).cardColor,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                ),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _AttendanceKpi(
                          label: s.allStudents,
                          value: '$totalCount',
                          color: Theme.of(context).colorScheme.onSurface,
                        ),
                        _AttendanceKpi(
                          label: s.present,
                          value: '$presentCount',
                          color: RaadColors.green,
                        ),
                        _AttendanceKpi(
                          label: s.absent,
                          value: '$absentCount',
                          color: absentCount > 0 ? RaadColors.red : context.muted,
                        ),
                        _AttendanceKpi(
                          label: s.attendanceRate,
                          value: '$rate%',
                          color: RaadColors.primary,
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(
                        value: totalCount > 0 ? presentCount / totalCount : 0.0,
                        minHeight: 6,
                        backgroundColor: context.muted.withValues(alpha: 0.15),
                        valueColor: const AlwaysStoppedAnimation<Color>(RaadColors.green),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              // Filter Chips
              Row(
                children: [
                  ChoiceChip(
                    label: Text('${s.allStudents} ($totalCount)'),
                    selected: _filter == 'all',
                    onSelected: (_) => setState(() => _filter = 'all'),
                  ),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: Text('${s.present} ($presentCount)'),
                    selected: _filter == 'present',
                    selectedColor: RaadColors.green.withValues(alpha: 0.2),
                    onSelected: (_) => setState(() => _filter = 'present'),
                  ),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: Text('${s.absent} ($absentCount)'),
                    selected: _filter == 'absent',
                    selectedColor: RaadColors.red.withValues(alpha: 0.2),
                    onSelected: (_) => setState(() => _filter = 'absent'),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Passengers list
              if (passengers.isEmpty)
                Card(
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                    side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
                    child: Column(
                      children: [
                        Icon(Icons.people_outline_rounded, size: 48, color: context.muted),
                        const SizedBox(height: 12),
                        Text(
                          s.noPassengersYet,
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Khadkan weli arday laguma qorin. Isticmaal badhanka hoose si aad arday ugu darto khadkaaga.',
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: 12.5, color: context.muted),
                        ),
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          icon: const Icon(Icons.add_location_alt_rounded),
                          label: Text(s.assignStudentStop),
                          onPressed: () => _openAssignStudentStopModal(
                            context,
                            widget.trip.routeId,
                            widget.trip.vehicle?.id,
                          ),
                        ),
                      ],
                    ),
                  ),
                )
              else if (filteredPassengers.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 40),
                  child: Center(
                    child: Text(
                      'Ma jiraan arday ku habboon shaandhayntan.',
                      style: TextStyle(color: context.muted),
                    ),
                  ),
                )
              else
                Card(
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                    side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
                  ),
                  child: ListView.separated(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: filteredPassengers.length,
                    separatorBuilder: (_, __) => const Divider(height: 1, indent: 56),
                    itemBuilder: (context, index) {
                      final p = filteredPassengers[index];
                      return _PassengerAttendanceTile(
                        passenger: p,
                        record: attendanceMap[p.studentId],
                        isPending: _pendingToggles.contains(p.studentId),
                        onToggle: () {
                          final isPresent = attendanceMap[p.studentId]?.isPresent == true;
                          _toggleAttendance(p, isPresent);
                        },
                      );
                    },
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _AttendanceKpi extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _AttendanceKpi({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          value,
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: TextStyle(
            fontSize: 11,
            color: context.muted,
          ),
        ),
      ],
    );
  }
}

class _AssignStudentStopSheet extends ConsumerStatefulWidget {
  final String? initialRouteId;
  final String? initialVehicleId;

  const _AssignStudentStopSheet({
    this.initialRouteId,
    this.initialVehicleId,
  });

  @override
  ConsumerState<_AssignStudentStopSheet> createState() =>
      _AssignStudentStopSheetState();
}

class _AssignStudentStopSheetState
    extends ConsumerState<_AssignStudentStopSheet> {
  String? _selectedRouteId;
  String? _selectedStudentId;
  final _stopNameController = TextEditingController();
  final _latController = TextEditingController();
  final _lngController = TextEditingController();
  final _radiusController = TextEditingController(text: '500');
  bool _fetchingGps = false;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _selectedRouteId = widget.initialRouteId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _fetchLivePhoneGps(silent: true);
    });
  }

  @override
  void dispose() {
    _stopNameController.dispose();
    _latController.dispose();
    _lngController.dispose();
    _radiusController.dispose();
    super.dispose();
  }

  Future<void> _fetchLivePhoneGps({bool silent = false}) async {
    final s = ref.read(stringsProvider);
    setState(() => _fetchingGps = true);
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        if (!silent && mounted) {
          showNotice(context, s.enableGpsPrompt, isError: true);
        }
        return;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          if (!silent && mounted) {
            showNotice(context, s.enableGpsPrompt, isError: true);
          }
          return;
        }
      }
      if (permission == LocationPermission.deniedForever) {
        if (!silent && mounted) {
          showNotice(context, s.enableGpsPrompt, isError: true);
        }
        return;
      }

      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 10),
      );
      if (mounted) {
        setState(() {
          _latController.text = position.latitude.toStringAsFixed(6);
          _lngController.text = position.longitude.toStringAsFixed(6);
          _radiusController.text = '500';
        });
        if (!silent) {
          showNotice(
            context,
            '${s.gpsCaptured}: ${position.latitude.toStringAsFixed(5)}, ${position.longitude.toStringAsFixed(5)}',
          );
        }
      }
    } catch (e) {
      if (!silent && mounted) {
        showNotice(context, '${s.enableGpsPrompt} ($e)', isError: true);
      }
    } finally {
      if (mounted) setState(() => _fetchingGps = false);
    }
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_selectedRouteId == null || _selectedRouteId!.isEmpty) {
      showNotice(context, s.adminSelectRoute, isError: true);
      return;
    }
    if (_selectedStudentId == null || _selectedStudentId!.isEmpty) {
      showNotice(context, s.selectStudent, isError: true);
      return;
    }
    final lat = double.tryParse(_latController.text.trim());
    final lng = double.tryParse(_lngController.text.trim());
    if (lat == null || lng == null) {
      showNotice(context, 'Fadlan geli ama qabo Latitude iyo Longitude sax ah', isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(repositoryProvider).assignStudentStop(
            studentId: _selectedStudentId!,
            routeId: _selectedRouteId!,
            latitude: lat,
            longitude: lng,
            stopName: _stopNameController.text.trim(),
            radiusM: 500,
          );
      if (mounted) {
        showNotice(context, s.studentStopAssigned);
        Navigator.of(context).pop();
        ref.invalidate(driverTripsProvider);
        ref.invalidate(driverStudentsProvider(widget.initialVehicleId));
      }
    } catch (err) {
      if (mounted) showError(context, err, s);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final routesAsync = ref.watch(driverRoutesProvider);
    final studentsAsync = ref.watch(driverStudentsProvider(widget.initialVehicleId));

    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    s.assignStudentStop,
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const Divider(),
            const SizedBox(height: 8),

            // Select Route Dropdown
            Text(s.adminSelectRoute, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                borderRadius: BorderRadius.circular(10),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  isExpanded: true,
                  hint: Text(s.adminSelectRoute),
                  value: _selectedRouteId,
                  items: [
                    for (final r in (routesAsync.valueOrNull ?? <DriverRouteOption>[]))
                      DropdownMenuItem(
                        value: r.id,
                        child: Text('${r.name} (${r.stopCount} stops)'),
                      ),
                  ],
                  onChanged: (val) => setState(() => _selectedRouteId = val),
                ),
              ),
            ),
            const SizedBox(height: 12),

            // Select Student Dropdown
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(s.selectStudent, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                if (studentsAsync.isLoading)
                  const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            if (studentsAsync.hasError) ...[
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Lama heli karo liiska ardayda waqtigan.',
                        style: TextStyle(color: RaadColors.red, fontSize: 12),
                      ),
                    ),
                    TextButton.icon(
                      icon: const Icon(Icons.refresh_rounded, size: 16),
                      label: Text(s.retry),
                      onPressed: () => ref.invalidate(driverStudentsProvider(widget.initialVehicleId)),
                    ),
                  ],
                ),
              ),
            ] else ...[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(
                  border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    hint: Text(
                      studentsAsync.isLoading
                          ? '${s.selectStudent}...'
                          : ((studentsAsync.valueOrNull?.isEmpty ?? true)
                              ? s.emptyState
                              : s.selectStudent),
                    ),
                    value: _selectedStudentId,
                    items: [
                      for (final st in (studentsAsync.valueOrNull ?? <DriverStudentOption>[]))
                        DropdownMenuItem(
                          value: st.id,
                          child: Text(
                            st.currentRouteName != null
                                ? '${st.fullName} (${st.currentRouteName})'
                                : st.fullName,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: (val) {
                      setState(() {
                        _selectedStudentId = val;
                        final student = studentsAsync.valueOrNull?.where((e) => e.id == val).firstOrNull;
                        if (student != null && _stopNameController.text.isEmpty) {
                          _stopNameController.text = 'Guriga ${student.fullName}';
                        }
                      });
                    },
                  ),
                ),
              ),
            ],
            const SizedBox(height: 12),

            // Live Phone GPS Button
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    icon: _fetchingGps
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.my_location_rounded, size: 18),
                    label: Text(
                      _fetchingGps ? '${s.capturePhoneGps}...' : s.capturePhoneGps,
                      style: const TextStyle(fontSize: 12.5),
                    ),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      foregroundColor: RaadColors.primary,
                      side: BorderSide(color: RaadColors.primary.withValues(alpha: 0.5)),
                    ),
                    onPressed: _fetchingGps ? null : () => _fetchLivePhoneGps(silent: false),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Lat & Lng input fields
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _latController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      labelText: s.adminLatitude,
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _lngController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(
                      labelText: s.adminLongitude,
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // Radius Fixed Display
            TextField(
              controller: _radiusController,
              readOnly: true,
              decoration: InputDecoration(
                labelText: s.proximityNotice500m,
                suffixText: 'm',
                prefixIcon: const Icon(Icons.radar_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Stop Name
            TextField(
              controller: _stopNameController,
              decoration: InputDecoration(
                labelText: s.adminStopNameLabel,
                prefixIcon: const Icon(Icons.place_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 18),

            FilledButton(
              onPressed: _submitting ? null : _submit,
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text(s.save),
            ),
          ],
        ),
      ),
    );
  }
}
