import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../common/notifications_screen.dart';
import '../common/profile_screen.dart';
import 'admin_data.dart';

/// The Organization Admin's view of their own school's transport (ADR-0062): what is running,
/// what needs attention, and which buses are connected. It reads; managing is done on the web
/// dashboard. No live video here: on mobile that stays the per-parent grant of ADR-0026.
class AdminShell extends ConsumerStatefulWidget {
  const AdminShell({super.key});

  @override
  ConsumerState<AdminShell> createState() => _AdminShellState();
}

class _AdminShellState extends ConsumerState<AdminShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    ref.watch(notificationsLiveProvider);
    final unread = ref.watch(unreadCountProvider);
    final alerts = ref.watch(adminAlertsProvider).valueOrNull?.length ?? 0;
    final pages = [
      AdminOverviewScreen(onOpenTab: (index) => setState(() => _index = index)),
      const AdminTodayScreen(),
      const AdminAlertsScreen(),
      const NotificationsScreen(splitByKind: false),
      ProfileScreen(
        title: s.profile,
        extra: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 12, 4, 0),
            child: Text(s.adminManageOnWeb,
                style: TextStyle(fontSize: 12.5, color: context.muted)),
          ),
        ],
      ),
    ];
    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: [
          NavigationDestination(
              icon: const Icon(Icons.dashboard_rounded), label: s.navOverview),
          NavigationDestination(
              icon: const Icon(Icons.today_rounded), label: s.navToday),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: alerts > 0,
              label: Text('$alerts'),
              child: const Icon(Icons.shield_rounded),
            ),
            label: s.navAlerts,
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
              icon: const Icon(Icons.person_rounded), label: s.navProfile),
        ],
      ),
    );
  }
}

const adminTodayTab = 1;
const adminAlertsTab = 2;

class AdminOverviewScreen extends ConsumerWidget {
  final void Function(int index) onOpenTab;
  const AdminOverviewScreen({super.key, required this.onOpenTab});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final overview = ref.watch(adminOverviewProvider);
    final board = ref.watch(adminBoardProvider).valueOrNull;
    final alerts = ref.watch(adminAlertsProvider).valueOrNull;
    final fleet = ref.watch(adminFleetOnlineProvider);

    Future<void> refresh() async {
      ref.invalidate(adminOverviewProvider);
      ref.invalidate(adminBoardProvider);
      ref.invalidate(adminAlertsProvider);
      ref.invalidate(adminFleetOnlineProvider);
      await ref.read(adminOverviewProvider.future);
    }

    return Scaffold(
      appBar: AppBar(title: Text(s.adminOverviewTitle)),
      body: AsyncBody<AdminOverview>(
        value: overview,
        onRetry: refresh,
        builder: (data) => RefreshIndicator(
          onRefresh: refresh,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
            children: [
              SectionTitle(s.adminNeedsAttention),
              _AttentionCard(
                uncovered: board?.uncoveredTrips ?? 0,
                openAlerts: alerts?.length ?? 0,
                onOpenTab: onOpenTab,
              ),
              SectionTitle(s.adminFleet),
              _KpiRow(children: [
                _Kpi(
                    icon: Icons.directions_bus_rounded,
                    label: s.adminVehicles,
                    value: data.vehicles),
                _Kpi(
                    icon: Icons.wifi_tethering_rounded,
                    label: s.adminOnlineNow,
                    value: data.onlineNow,
                    color: RaadColors.green),
                _Kpi(
                    icon: Icons.play_circle_outline_rounded,
                    label: s.adminTripsInProgress,
                    value: data.tripsInProgress),
              ]),
              SectionTitle(s.adminPeople),
              _KpiRow(children: [
                _Kpi(
                    icon: Icons.school_rounded,
                    label: s.adminStudents,
                    value: data.students),
                _Kpi(
                    icon: Icons.badge_rounded,
                    label: s.adminDrivers,
                    value: data.drivers),
                _Kpi(
                    icon: Icons.alt_route_rounded,
                    label: s.adminRoutes,
                    value: data.routes),
              ]),
              SectionTitle(s.adminOnlineBuses),
              fleet.when(
                skipLoadingOnRefresh: true,
                loading: () => const SectionCard(
                    child: SizedBox(height: 48, child: LoadingView())),
                error: (error, _) =>
                    SectionCard(child: Text(errorMessage(error, s))),
                data: (online) => _OnlineBuses(online: online),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AttentionCard extends ConsumerWidget {
  final int uncovered;
  final int openAlerts;
  final void Function(int index) onOpenTab;
  const _AttentionCard(
      {required this.uncovered,
      required this.openAlerts,
      required this.onOpenTab});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    if (uncovered == 0 && openAlerts == 0) {
      return SectionCard(
        child: Row(
          children: [
            const Icon(Icons.check_circle_rounded, color: RaadColors.green),
            const SizedBox(width: 12),
            Expanded(child: Text(s.adminAllClear)),
          ],
        ),
      );
    }
    Widget row(IconData icon, Color color, String text, int tab) {
      return InkWell(
        onTap: () => onOpenTab(tab),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Icon(icon, color: color),
              const SizedBox(width: 12),
              Expanded(
                child: Text(text,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
              ),
              Icon(Icons.chevron_right_rounded, color: context.muted),
            ],
          ),
        ),
      );
    }

    return SectionCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          if (openAlerts > 0)
            row(Icons.shield_rounded, RaadColors.red,
                s.adminOpenAlerts(openAlerts), adminAlertsTab),
          if (openAlerts > 0 && uncovered > 0) const Divider(height: 1),
          if (uncovered > 0)
            row(Icons.person_off_rounded, RaadColors.amber,
                s.adminUncoveredTrips(uncovered), adminTodayTab),
        ],
      ),
    );
  }
}

class _KpiRow extends StatelessWidget {
  final List<Widget> children;
  const _KpiRow({required this.children});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < children.length; i++) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(child: children[i]),
        ],
      ],
    );
  }
}

class _Kpi extends StatelessWidget {
  final IconData icon;
  final String label;

  /// Null when the figure could not be read: shown as a dash, never as zero.
  final int? value;
  final Color? color;
  const _Kpi(
      {required this.icon,
      required this.label,
      required this.value,
      this.color});

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: color ?? context.colors.primary),
          const SizedBox(height: 10),
          Text(
            value?.toString() ?? '—',
            style: const TextStyle(
                fontSize: 24, fontWeight: FontWeight.w800, height: 1.1),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 12, color: context.muted),
          ),
        ],
      ),
    );
  }
}

class _OnlineBuses extends ConsumerWidget {
  final FleetOnline online;
  const _OnlineBuses({required this.online});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    if (online.vehicles.isEmpty) {
      return SectionCard(
        child: Text(s.adminNoBusOnline, style: TextStyle(color: context.muted)),
      );
    }
    return SectionCard(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        children: [
          for (final vehicle in online.vehicles)
            ListTile(
              dense: true,
              leading:
                  const Icon(Icons.circle, size: 12, color: RaadColors.green),
              title: Text(vehicle.displayName,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
          if (online.totalOnline > online.vehicles.length)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
              child: Text(
                s.adminShowingOf(online.vehicles.length, online.totalOnline),
                style: TextStyle(fontSize: 12.5, color: context.muted),
              ),
            ),
        ],
      ),
    );
  }
}

class AdminTodayScreen extends ConsumerWidget {
  const AdminTodayScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final board = ref.watch(adminBoardProvider);
    final names = ref.watch(adminVehicleNamesProvider).valueOrNull ?? const {};

    Future<void> refresh() async {
      ref.invalidate(adminBoardProvider);
      ref.invalidate(adminVehicleNamesProvider);
      await ref.read(adminBoardProvider.future);
    }

    return Scaffold(
      appBar: AppBar(title: Text(s.adminTodayTitle)),
      body: AsyncBody<DailyBoard>(
        value: board,
        onRetry: refresh,
        builder: (data) {
          final buses = data.vehicles.where((v) => v.trips.isNotEmpty).toList();
          return RefreshIndicator(
            onRefresh: refresh,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
              children: [
                if (data.closures.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: SectionCard(
                      child: Row(
                        children: [
                          const Icon(Icons.event_busy_rounded,
                              color: RaadColors.amber),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                                '${s.adminClosedToday}: ${data.closures.join(', ')}'),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (buses.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: EmptyView(
                        icon: Icons.event_available_rounded,
                        message: s.adminNoTripsToday),
                  ),
                for (final bus in buses)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: _BusCard(
                        bus: bus, name: names[bus.vehicleId] ?? bus.vehicleId),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _BusCard extends ConsumerWidget {
  final BoardVehicle bus;
  final String name;
  const _BusCard({required this.bus, required this.name});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.directions_bus_rounded, color: context.colors.primary),
              const SizedBox(width: 10),
              Expanded(
                child: Text(name,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w800)),
              ),
              Text(s.adminTripCount(bus.trips.length),
                  style: TextStyle(fontSize: 12.5, color: context.muted)),
            ],
          ),
          for (final trip in bus.trips) ...[
            const Divider(height: 24),
            _TripRow(trip: trip),
          ],
          if (bus.crew.isNotEmpty) ...[
            const Divider(height: 24),
            Text(s.adminCrew,
                style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: context.muted)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                for (final member in bus.crew)
                  StatusChip(
                    label: [
                      member.name,
                      if (member.roleName != null) member.roleName!,
                      if (member.isSubstitute) s.adminSubstitute,
                      if (member.isUnavailable) s.adminAbsent,
                    ].join(' · '),
                    color:
                        member.isUnavailable ? RaadColors.amber : context.muted,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _TripRow extends ConsumerWidget {
  final BoardTrip trip;
  const _TripRow({required this.trip});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final uncovered = trip.uncoveredReason != null;
    final departure = shortTime(trip.plannedDeparture);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                [s.tripType(trip.tripType), if (departure != null) departure]
                    .join(' · '),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            StatusChip(
                label: s.tripStatus(trip.status),
                color: tripStatusColor(trip.status)),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          [
            if (trip.routeName != null) trip.routeName!,
            trip.driverName ?? s.adminNoDriver,
          ].join(' · '),
          style: TextStyle(color: context.muted),
        ),
        if (uncovered)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(
              children: [
                const Icon(Icons.warning_amber_rounded,
                    size: 18, color: RaadColors.amber),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    s.adminUncoveredReason(trip.uncoveredReason!),
                    style: const TextStyle(
                        color: RaadColors.amber, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
        if (trip.status == 'cancelled' && trip.cancelledReason != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(trip.cancelledReason!,
                style: TextStyle(color: context.muted)),
          ),
      ],
    );
  }
}

class AdminAlertsScreen extends ConsumerWidget {
  const AdminAlertsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final alerts = ref.watch(adminAlertsProvider);
    final names = ref.watch(adminVehicleNamesProvider).valueOrNull ?? const {};

    Future<void> refresh() async {
      ref.invalidate(adminAlertsProvider);
      await ref.read(adminAlertsProvider.future);
    }

    return Scaffold(
      appBar: AppBar(title: Text(s.adminAlertsTitle)),
      body: AsyncBody<List<SafetyAlert>>(
        value: alerts,
        onRetry: refresh,
        builder: (data) => RefreshIndicator(
          onRefresh: refresh,
          child: data.isEmpty
              ? ListView(
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 120),
                      child: EmptyView(
                          icon: Icons.verified_user_outlined,
                          message: s.adminNoAlerts),
                    ),
                  ],
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                  itemCount: data.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final alert = data[index];
                    return _AlertCard(
                        alert: alert,
                        vehicleName: names[alert.vehicleId] ?? alert.vehicleId);
                  },
                ),
        ),
      ),
    );
  }
}

class _AlertCard extends ConsumerWidget {
  final SafetyAlert alert;
  final String vehicleName;
  const _AlertCard({required this.alert, required this.vehicleName});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final tone = alert.isCritical ? RaadColors.red : RaadColors.amber;
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                  alert.isCritical
                      ? Icons.emergency_rounded
                      : Icons.warning_amber_rounded,
                  color: tone),
              const SizedBox(width: 10),
              Expanded(
                child: Text(s.alarmTypeName(alert.alarmType),
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w800)),
              ),
              StatusChip(
                label: s.adminAlertStatus(alert.status),
                color: alert.status == 'open' ? tone : context.muted,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(vehicleName,
              style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text(
            [
              if (alert.lastRaisedAt != null)
                friendlyMoment(alert.lastRaisedAt!, s),
              if (alert.occurrences > 1) s.adminOccurrences(alert.occurrences),
              if (alert.isLate) s.adminLateAlert,
            ].join(' · '),
            style: TextStyle(fontSize: 12.5, color: context.muted),
          ),
          if (alert.isCritical)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: StatusChip(label: s.adminCritical, color: RaadColors.red),
            ),
        ],
      ),
    );
  }
}
