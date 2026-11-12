import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../common/notifications_screen.dart';
import '../common/profile_screen.dart';
import 'admin_finance_screen.dart';
import 'admin_fleet_map_screen.dart';
import 'admin_routes_screen.dart';
import 'admin_staff_screen.dart';
import 'admin_trips_screen.dart';

export 'admin_multi_camera_screen.dart';

/// Top App Bar actions helper providing uniform Refresh, Notification and Profile icons.
List<Widget> adminTopActions(
  BuildContext context,
  WidgetRef ref, {
  VoidCallback? onRefresh,
}) {
  final s = ref.watch(stringsProvider);
  final unread = ref.watch(unreadCountProvider);
  return [
    if (onRefresh != null)
      IconButton(
        icon: const Icon(Icons.refresh_rounded),
        tooltip: s.retry,
        onPressed: onRefresh,
      ),
    IconButton(
      icon: Badge(
        isLabelVisible: unread > 0,
        label: Text('$unread'),
        child: const Icon(Icons.notifications_outlined),
      ),
      tooltip: s.navNotifications,
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => const NotificationsScreen(splitByKind: false),
        ),
      ),
    ),
    IconButton(
      icon: const Icon(Icons.account_circle_outlined),
      tooltip: s.profile,
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => ProfileScreen(title: s.profile)),
      ),
    ),
  ];
}

/// The Organization Admin's mobile shell (ADR-0062).
/// Completely restructured into the 5 core operational pillars:
/// 1. Daba-gal (Live Tracking, Map, Video & Two-Way Intercom)
/// 2. Safarro (Trips Management, Dispatch & Real-Time Bus Search)
/// 3. Maaliyad (ERP School Finance, Invoices & Mobile Payments)
/// 4. Khadad (Routes & Stops)
/// 5. Shaqaale (Drivers, Staff & Bus Crew Assignment)
class AdminShell extends ConsumerStatefulWidget {
  const AdminShell({super.key});

  @override
  ConsumerState<AdminShell> createState() => _AdminShellState();
}

class _AdminShellState extends ConsumerState<AdminShell> {
  int _index = 0;

  final _pages = const [
    AdminFleetMapScreen(),
    AdminTripsScreen(),
    AdminFinanceScreen(),
    AdminRoutesScreen(),
    AdminStaffScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    ref.watch(notificationsLiveProvider);

    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: NavigationBarTheme(
        data: NavigationBarThemeData(
          height: 64,
          elevation: 3,
          labelTextStyle: WidgetStateProperty.resolveWith((states) {
            final isSelected = states.contains(WidgetState.selected);
            return TextStyle(
              fontSize: 11.0,
              fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              letterSpacing: -0.2,
              color: isSelected ? Theme.of(context).primaryColor : null,
            );
          }),
          iconTheme: WidgetStateProperty.resolveWith((states) {
            final isSelected = states.contains(WidgetState.selected);
            return IconThemeData(
              size: 22.0,
              color: isSelected ? Theme.of(context).primaryColor : null,
            );
          }),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: (idx) => setState(() => _index = idx),
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          destinations: [
            NavigationDestination(
              icon: const Icon(Icons.location_on_outlined),
              selectedIcon: const Icon(Icons.location_on_rounded),
              label: s.adminNavPillarLive,
            ),
            NavigationDestination(
              icon: const Icon(Icons.directions_bus_outlined),
              selectedIcon: const Icon(Icons.directions_bus_rounded),
              label: s.adminNavPillarTrips,
            ),
            NavigationDestination(
              icon: const Icon(Icons.account_balance_wallet_outlined),
              selectedIcon: const Icon(Icons.account_balance_wallet_rounded),
              label: s.adminNavPillarFinance,
            ),
            NavigationDestination(
              icon: const Icon(Icons.alt_route_rounded),
              selectedIcon: const Icon(Icons.alt_route_rounded),
              label: s.adminNavPillarRoutes,
            ),
            NavigationDestination(
              icon: const Icon(Icons.badge_outlined),
              selectedIcon: const Icon(Icons.badge_rounded),
              label: s.adminNavPillarStaff,
            ),
          ],
        ),
      ),
    );
  }
}
