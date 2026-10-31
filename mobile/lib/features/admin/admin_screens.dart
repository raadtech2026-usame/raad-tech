import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import '../common/notifications_screen.dart';
import '../common/profile_screen.dart';
import 'admin_data.dart';

/// The Organization Admin's view of their own school's transport (ADR-0062).
/// Upgraded to provide complete management parity with the web dashboard:
/// Users (Drivers, Parents, Students), Fleet (Vehicles, Device Linking),
/// Dispatch & Routes, and Safety Alerts.
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
          const SizedBox(height: 12),
          ListTile(
            leading: const Icon(Icons.people_rounded),
            title: Text(s.adminNavUsers),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminUsersScreen()),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.directions_bus_rounded),
            title: Text(s.adminNavFleet),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminFleetScreen()),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.alt_route_rounded),
            title: Text(s.adminNavDispatch),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminDispatchScreen()),
            ),
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
      appBar: AppBar(
        title: Text(s.adminOverviewTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.people_rounded),
            tooltip: s.adminNavUsers,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminUsersScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.directions_bus_rounded),
            tooltip: s.adminNavFleet,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminFleetScreen()),
            ),
          ),
        ],
      ),
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
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.people_rounded, size: 18),
                      label: Text(s.adminNavUsers),
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) => const AdminUsersScreen()),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.directions_bus_rounded, size: 18),
                      label: Text(s.adminNavFleet),
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) => const AdminFleetScreen()),
                      ),
                    ),
                  ),
                ],
              ),
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
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: color ?? context.muted),
          const SizedBox(height: 8),
          Text(
            value == null ? '—' : '$value',
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 2),
          Text(label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: context.muted)),
        ],
      ),
    );
  }
}

class _OnlineBuses extends StatelessWidget {
  final FleetOnline online;
  const _OnlineBuses({required this.online});

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    if (online.vehicles.isEmpty) {
      return SectionCard(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Text(s.adminNoBusOnline,
              style: TextStyle(color: context.muted, fontSize: 13)),
        ),
      );
    }
    return SectionCard(
      padding: EdgeInsets.zero,
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
      appBar: AppBar(
        title: Text(s.adminTodayTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.alt_route_rounded),
            tooltip: s.adminNavDispatch,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminDispatchScreen()),
            ),
          ),
        ],
      ),
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

// ============================================================================
// USERS & DIRECTORY SCREEN (Drivers, Parents, Students)
// ============================================================================

class AdminUsersScreen extends ConsumerStatefulWidget {
  const AdminUsersScreen({super.key});

  @override
  ConsumerState<AdminUsersScreen> createState() => _AdminUsersScreenState();
}

class _AdminUsersScreenState extends ConsumerState<AdminUsersScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminNavUsers),
        bottom: TabBar(
          controller: _tabController,
          tabs: [
            Tab(text: s.adminTabDrivers),
            Tab(text: s.adminTabParents),
            Tab(text: s.adminTabStudents),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: const [
          _DriversTab(),
          _ParentsTab(),
          _StudentsTab(),
        ],
      ),
    );
  }
}

class _DriversTab extends ConsumerWidget {
  const _DriversTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final drivers = ref.watch(adminDriversProvider);

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.person_add_rounded),
        label: Text(s.adminAddDriver),
        onPressed: () => _showAddDriverSheet(context, ref, s),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(adminDriversProvider),
        child: drivers.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(s.somethingWrong)),
          data: (list) {
            if (list.isEmpty) {
              return Center(child: Text(s.adminDrivers));
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final d = list[i];
                return SectionCard(
                  child: Row(
                    children: [
                      CircleAvatar(
                        backgroundColor: d.isActive
                            ? RaadColors.brandPrimary.withValues(alpha: 0.15)
                            : Colors.grey.withValues(alpha: 0.2),
                        child: Icon(Icons.badge_rounded,
                            color: d.isActive ? RaadColors.brandPrimary : Colors.grey),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(d.fullName,
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 15)),
                            const SizedBox(height: 2),
                            Text(
                              '${d.phone}${d.licenseNo != null ? ' · ${d.licenseNo}' : ''}',
                              style: TextStyle(
                                  fontSize: 12.5, color: context.muted),
                            ),
                          ],
                        ),
                      ),
                      PopupMenuButton<String>(
                        onSelected: (val) async {
                          await ref
                              .read(adminRepositoryProvider)
                              .updateDriverStatus(d.id, val);
                          ref.invalidate(adminDriversProvider);
                        },
                        itemBuilder: (ctx) => [
                          PopupMenuItem(
                            value: 'active',
                            child: Text(s.adminStatusActive),
                          ),
                          PopupMenuItem(
                            value: 'inactive',
                            child: Text(s.adminStatusInactive),
                          ),
                        ],
                        child: StatusChip(
                          label: d.isActive
                              ? s.adminStatusActive
                              : s.adminStatusInactive,
                          color: d.isActive ? RaadColors.green : RaadColors.amber,
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

class _ParentsTab extends ConsumerWidget {
  const _ParentsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final parents = ref.watch(adminParentsProvider);

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.person_add_alt_1_rounded),
        label: Text(s.adminAddParent),
        onPressed: () => _showAddParentSheet(context, ref, s),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(adminParentsProvider),
        child: parents.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(s.somethingWrong)),
          data: (list) {
            if (list.isEmpty) {
              return Center(child: Text(s.adminTabParents));
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final p = list[i];
                return SectionCard(
                  child: Row(
                    children: [
                      CircleAvatar(
                        backgroundColor: RaadColors.blue.withValues(alpha: 0.15),
                        child: const Icon(Icons.family_restroom_rounded,
                            color: RaadColors.blue),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(p.fullName,
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 15)),
                            const SizedBox(height: 2),
                            Text(
                              p.phone + (p.email != null ? ' · ${p.email}' : ''),
                              style: TextStyle(
                                  fontSize: 12.5, color: context.muted),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

class _StudentsTab extends ConsumerWidget {
  const _StudentsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final students = ref.watch(adminStudentsProvider);

    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.school_rounded),
        label: Text(s.adminEnrollStudent),
        onPressed: () => _showEnrollStudentSheet(context, ref, s),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(adminStudentsProvider),
        child: students.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(s.somethingWrong)),
          data: (list) {
            if (list.isEmpty) {
              return Center(child: Text(s.adminTabStudents));
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final st = list[i];
                return SectionCard(
                  child: Row(
                    children: [
                      CircleAvatar(
                        backgroundColor: RaadColors.brandPrimary.withValues(alpha: 0.15),
                        child: const Icon(Icons.school_rounded,
                            color: RaadColors.brandPrimary),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(st.fullName,
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 15)),
                            const SizedBox(height: 2),
                            Text(
                              '${st.externalRef ?? s.notAvailable}${st.gender != null ? ' · ${st.gender}' : ''}',
                              style: TextStyle(
                                  fontSize: 12.5, color: context.muted),
                            ),
                          ],
                        ),
                      ),
                      PopupMenuButton<String>(
                        onSelected: (status) async {
                          await ref
                              .read(adminRepositoryProvider)
                              .updateStudentStatus(st.id, status);
                          ref.invalidate(adminStudentsProvider);
                        },
                        itemBuilder: (ctx) => [
                          PopupMenuItem(
                            value: 'active',
                            child: Text(s.adminStatusActive),
                          ),
                          PopupMenuItem(
                            value: 'disabled',
                            child: Text(s.adminStatusInactive),
                          ),
                          PopupMenuItem(
                            value: 'graduated',
                            child: Text(s.adminStatusGraduated),
                          ),
                          PopupMenuItem(
                            value: 'transferred',
                            child: Text(s.adminStatusWithdrawn),
                          ),
                        ],
                        child: StatusChip(
                          label: st.isActive
                              ? s.adminStatusActive
                              : st.status,
                          color: st.isActive ? RaadColors.green : RaadColors.amber,
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

// ============================================================================
// FLEET & VEHICLES MANAGEMENT SCREEN
// ============================================================================

class AdminFleetScreen extends ConsumerWidget {
  const AdminFleetScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final vehicles = ref.watch(adminVehiclesListProvider);
    final fleetOnline = ref.watch(adminFleetOnlineProvider).valueOrNull;

    final onlineIds = fleetOnline?.vehicles.map((v) => v.vehicleId).toSet() ?? {};

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminNavFleet),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_rounded),
        label: Text(s.adminAddVehicle),
        onPressed: () => _showAddVehicleSheet(context, ref, s),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(adminVehiclesListProvider);
          ref.invalidate(adminFleetOnlineProvider);
        },
        child: vehicles.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(s.somethingWrong)),
          data: (list) {
            if (list.isEmpty) {
              return Center(child: Text(s.adminNoBusOnline));
            }
            return ListView.separated(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final v = list[i];
                final isOnline = onlineIds.contains(v.id);
                return SectionCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CircleAvatar(
                            backgroundColor: isOnline
                                ? RaadColors.green.withValues(alpha: 0.15)
                                : Colors.grey.withValues(alpha: 0.15),
                            child: Icon(Icons.directions_bus_rounded,
                                color: isOnline
                                    ? RaadColors.green
                                    : Colors.grey),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(v.displayName,
                                    style: const TextStyle(
                                        fontWeight: FontWeight.bold,
                                        fontSize: 15)),
                                const SizedBox(height: 2),
                                Text(
                                  '${v.capacity ?? '—'} ${s.adminCapacity} · ${isOnline ? s.adminOnlineNow : s.adminStatusInactive}',
                                  style: TextStyle(
                                      fontSize: 12, color: context.muted),
                                ),
                              ],
                            ),
                          ),
                          PopupMenuButton<String>(
                            onSelected: (status) async {
                              await ref
                                  .read(adminRepositoryProvider)
                                  .updateVehicleStatus(v.id, status);
                              ref.invalidate(adminVehiclesListProvider);
                            },
                            itemBuilder: (ctx) => [
                              PopupMenuItem(
                                value: 'active',
                                child: Text(s.adminStatusActive),
                              ),
                              PopupMenuItem(
                                value: 'maintenance',
                                child: Text(s.adminStatusMaintenance),
                              ),
                              PopupMenuItem(
                                value: 'inactive',
                                child: Text(s.adminStatusInactive),
                              ),
                            ],
                            child: StatusChip(
                              label: v.isMaintenance
                                  ? s.adminStatusMaintenance
                                  : (v.isActive
                                      ? s.adminStatusActive
                                      : s.adminStatusInactive),
                              color: v.isMaintenance
                                  ? RaadColors.amber
                                  : (v.isActive
                                      ? RaadColors.green
                                      : Colors.grey),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      const Divider(height: 1),
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Row(
                            children: [
                              Icon(Icons.router_rounded,
                                  size: 16, color: context.muted),
                              const SizedBox(width: 6),
                              Text(
                                v.terminalId != null
                                    ? '${s.adminDeviceLinked} (#${v.terminalId})'
                                    : s.adminNoDeviceLinked,
                                style: TextStyle(
                                    fontSize: 12, color: context.muted),
                              ),
                            ],
                          ),
                          TextButton.icon(
                            icon: const Icon(Icons.link_rounded, size: 16),
                            label: Text(s.adminLinkDevice,
                                style: const TextStyle(fontSize: 12)),
                            onPressed: () =>
                                _showLinkDeviceDialog(context, ref, v, s),
                          ),
                        ],
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

// ============================================================================
// DISPATCH & ROUTES SCREEN
// ============================================================================

class AdminDispatchScreen extends ConsumerWidget {
  const AdminDispatchScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final routes = ref.watch(adminRoutesProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminRoutesTitle),
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(adminRoutesProvider),
        child: routes.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(s.somethingWrong)),
          data: (list) {
            if (list.isEmpty) {
              return Center(child: Text(s.adminRoutesTitle));
            }
            return ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final r = list[i];
                return SectionCard(
                  child: Row(
                    children: [
                      CircleAvatar(
                        backgroundColor: RaadColors.brandPrimary.withValues(alpha: 0.12),
                        child: const Icon(Icons.alt_route_rounded,
                            color: RaadColors.brandPrimary),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(r.name,
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 15)),
                            const SizedBox(height: 2),
                            Text(
                              '${r.code != null ? '${r.code} · ' : ''}${s.adminStopsCount(r.stopCount)}',
                              style: TextStyle(
                                  fontSize: 12.5, color: context.muted),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

// ============================================================================
// DIALOGS & FORM BOTTOM SHEETS
// ============================================================================

void _showTempPasswordDialog(
    BuildContext context, String name, String password, Strings s) {
  showDialog(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.key_rounded, color: RaadColors.brandPrimary),
          const SizedBox(width: 8),
          Expanded(child: Text(s.adminTempPasswordTitle)),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('$name:'),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.grey.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: RaadColors.brandPrimary.withValues(alpha: 0.4)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: SelectableText(
                    password,
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontWeight: FontWeight.bold,
                      fontSize: 18,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.copy_rounded, size: 20),
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: password));
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(s.adminCopied)),
                    );
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Text(s.adminTempPasswordMsg,
              style: TextStyle(fontSize: 12, color: context.muted)),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(),
          child: Text(s.confirm),
        ),
      ],
    ),
  );
}

void _showAddDriverSheet(
    BuildContext context, WidgetRef ref, Strings s) {
  final nameCtrl = TextEditingController();
  final phoneCtrl = TextEditingController();
  final licenseCtrl = TextEditingController();
  final emailCtrl = TextEditingController();

  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => Padding(
      padding: EdgeInsets.fromLTRB(
          16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(s.adminAddDriver,
              style:
                  const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          TextField(
            controller: nameCtrl,
            decoration: InputDecoration(
                labelText: s.adminFullName, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: phoneCtrl,
            keyboardType: TextInputType.phone,
            decoration: InputDecoration(
                labelText: s.adminPhone, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: licenseCtrl,
            decoration: InputDecoration(
                labelText: s.adminLicenseNo, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: emailCtrl,
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(
                labelText: s.adminEmail, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () async {
              if (nameCtrl.text.isEmpty || phoneCtrl.text.isEmpty) return;
              Navigator.of(ctx).pop();
              try {
                final res = await ref.read(adminRepositoryProvider).createDriver(
                      fullName: nameCtrl.text.trim(),
                      phone: phoneCtrl.text.trim(),
                      licenseNo: licenseCtrl.text.trim(),
                      email: emailCtrl.text.trim(),
                    );
                ref.invalidate(adminDriversProvider);
                final tempPass = res['temporary_password'] as String?;
                if (tempPass != null && context.mounted) {
                  _showTempPasswordDialog(
                      context, nameCtrl.text.trim(), tempPass, s);
                }
              } catch (_) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(s.somethingWrong)),
                  );
                }
              }
            },
            child: Center(child: Text(s.save)),
          ),
        ],
      ),
    ),
  );
}

void _showAddParentSheet(
    BuildContext context, WidgetRef ref, Strings s) {
  final nameCtrl = TextEditingController();
  final phoneCtrl = TextEditingController();
  final emailCtrl = TextEditingController();

  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => Padding(
      padding: EdgeInsets.fromLTRB(
          16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(s.adminAddParent,
              style:
                  const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          TextField(
            controller: nameCtrl,
            decoration: InputDecoration(
                labelText: s.adminFullName, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: phoneCtrl,
            keyboardType: TextInputType.phone,
            decoration: InputDecoration(
                labelText: s.adminPhone, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: emailCtrl,
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(
                labelText: s.adminEmail, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () async {
              if (nameCtrl.text.isEmpty || phoneCtrl.text.isEmpty) return;
              Navigator.of(ctx).pop();
              try {
                final res = await ref.read(adminRepositoryProvider).createParent(
                      fullName: nameCtrl.text.trim(),
                      phone: phoneCtrl.text.trim(),
                      email: emailCtrl.text.trim(),
                    );
                ref.invalidate(adminParentsProvider);
                final tempPass = res['temporary_password'] as String?;
                if (tempPass != null && context.mounted) {
                  _showTempPasswordDialog(
                      context, nameCtrl.text.trim(), tempPass, s);
                }
              } catch (_) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(s.somethingWrong)),
                  );
                }
              }
            },
            child: Center(child: Text(s.save)),
          ),
        ],
      ),
    ),
  );
}

void _showEnrollStudentSheet(
    BuildContext context, WidgetRef ref, Strings s) {
  final nameCtrl = TextEditingController();
  final refCtrl = TextEditingController();
  String gender = 'male';

  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setModalState) => Padding(
        padding: EdgeInsets.fromLTRB(
            16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(s.adminEnrollStudent,
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            TextField(
              controller: nameCtrl,
              decoration: InputDecoration(
                  labelText: s.adminFullName,
                  border: const OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: refCtrl,
              decoration: InputDecoration(
                  labelText: s.adminAdmissionNo,
                  border: const OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: gender,
              decoration: InputDecoration(
                  labelText: s.adminGender,
                  border: const OutlineInputBorder()),
              items: [
                DropdownMenuItem(value: 'male', child: Text(s.adminMale)),
                DropdownMenuItem(value: 'female', child: Text(s.adminFemale)),
              ],
              onChanged: (val) {
                if (val != null) setModalState(() => gender = val);
              },
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () async {
                if (nameCtrl.text.isEmpty) return;
                Navigator.of(ctx).pop();
                try {
                  await ref.read(adminRepositoryProvider).enrollStudent(
                        fullName: nameCtrl.text.trim(),
                        externalRef: refCtrl.text.trim(),
                        gender: gender,
                      );
                  ref.invalidate(adminStudentsProvider);
                } catch (_) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(s.somethingWrong)),
                    );
                  }
                }
              },
              child: Center(child: Text(s.save)),
            ),
          ],
        ),
      ),
    ),
  );
}

void _showAddVehicleSheet(
    BuildContext context, WidgetRef ref, Strings s) {
  final plateCtrl = TextEditingController();
  final labelCtrl = TextEditingController();
  final capCtrl = TextEditingController();

  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => Padding(
      padding: EdgeInsets.fromLTRB(
          16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(s.adminAddVehicle,
              style:
                  const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          TextField(
            controller: plateCtrl,
            decoration: InputDecoration(
                labelText: s.adminPlateNo, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: labelCtrl,
            decoration: InputDecoration(
                labelText: s.adminLabel, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: capCtrl,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(
                labelText: s.adminCapacity, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () async {
              if (plateCtrl.text.isEmpty) return;
              Navigator.of(ctx).pop();
              try {
                await ref.read(adminRepositoryProvider).createVehicle(
                      plateNo: plateCtrl.text.trim(),
                      label: labelCtrl.text.trim(),
                      capacity: int.tryParse(capCtrl.text.trim()),
                    );
                ref.invalidate(adminVehiclesListProvider);
              } catch (_) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(s.somethingWrong)),
                  );
                }
              }
            },
            child: Center(child: Text(s.save)),
          ),
        ],
      ),
    ),
  );
}

void _showLinkDeviceDialog(
    BuildContext context, WidgetRef ref, AdminVehicle vehicle, Strings s) {
  showDialog(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(s.adminAssignDeviceTitle),
      content: SizedBox(
        width: double.maxFinite,
        child: Consumer(
          builder: (context, ref, child) {
            final devices = ref.watch(adminDevicesProvider);
            return devices.when(
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (_, __) => Text(s.somethingWrong),
              data: (list) {
                final unassigned =
                    list.where((d) => d.vehicleId == null).toList();
                if (unassigned.isEmpty) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(s.adminNoDeviceLinked,
                        style: TextStyle(color: context.muted)),
                  );
                }
                return ListView.builder(
                  shrinkWrap: true,
                  itemCount: unassigned.length,
                  itemBuilder: (ctx, i) {
                    final d = unassigned[i];
                    return ListTile(
                      leading: const Icon(Icons.router_rounded),
                      title: Text(d.terminalId),
                      subtitle: Text(d.model ?? d.status),
                      onTap: () async {
                        Navigator.of(ctx).pop();
                        try {
                          await ref
                              .read(adminRepositoryProvider)
                              .assignDevice(d.id, vehicle.id);
                          ref.invalidate(adminVehiclesListProvider);
                          ref.invalidate(adminDevicesProvider);
                        } catch (_) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(s.somethingWrong)),
                            );
                          }
                        }
                      },
                    );
                  },
                );
              },
            );
          },
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(),
          child: Text(s.cancel),
        ),
      ],
    ),
  );
}
