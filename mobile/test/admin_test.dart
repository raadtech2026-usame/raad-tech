import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:raad_mobile/app/app.dart';
import 'package:raad_mobile/core/auth/principal.dart';
import 'package:raad_mobile/features/admin/admin_data.dart';
import 'package:raad_mobile/features/admin/admin_screens.dart';
import 'package:raad_mobile/features/auth/change_password_screen.dart';
import 'package:raad_mobile/features/common/profile_screen.dart';
import 'package:raad_mobile/features/driver/driver_screens.dart';
import 'package:raad_mobile/features/parent/parent_screens.dart';
import 'package:raad_mobile/shared/widgets.dart';

import 'support.dart';

Principal _principal(String role, {bool mustChangePassword = false}) =>
    Principal(
        userId: 'u',
        role: role,
        organizationId: 'org-1',
        isPasswordChangeRequired: mustChangePassword);

FakeAdminRepository _busyDay() {
  return FakeAdminRepository()
    ..overviewData = const AdminOverview(
        vehicles: 12,
        onlineNow: 9,
        tripsInProgress: 4,
        students: 310,
        drivers: 14,
        routes: 8)
    ..vehicleList = const [
      AdminVehicle(
          id: 'v1', plateNo: 'AB-123', label: 'Bus A', status: 'active'),
    ]
    ..online = const FleetOnline(vehicles: [
      OnlineVehicle(vehicleId: 'v1', plateNo: 'AB-123', label: 'Bus A'),
    ], totalOnline: 9)
    ..board = const DailyBoard(
        closures: [],
        uncoveredTrips: 1,
        vehicles: [
          BoardVehicle(vehicleId: 'v1', crew: [
            BoardCrewMember(
                name: 'Hodan',
                roleName: 'Attendant',
                isSubstitute: true,
                isUnavailable: false),
          ], trips: [
            BoardTrip(
                id: 't1',
                tripType: 'morning',
                routeName: 'North route',
                plannedDeparture: '06:30:00',
                driverName: 'Cabdi',
                status: 'in_progress',
                cancelledReason: null,
                uncoveredReason: null),
            BoardTrip(
                id: 't2',
                tripType: 'afternoon',
                routeName: 'North route',
                plannedDeparture: '13:00:00',
                driverName: null,
                status: 'scheduled',
                cancelledReason: null,
                uncoveredReason: 'driver_unavailable'),
          ]),
        ])
    ..alerts = [
      SafetyAlert(
          id: 'a1',
          vehicleId: 'v1',
          alarmType: 'sos',
          isCritical: true,
          status: 'open',
          lastRaisedAt: DateTime.now(),
          isLate: false,
          occurrences: 3),
    ];
}

void main() {
  group('Where each role lands', () {
    test('parent, driver and organization admin each get their own shell', () {
      expect(homeForPrincipal(_principal('parent')), isA<ParentShell>());
      expect(homeForPrincipal(_principal('driver')), isA<DriverShell>());
      expect(homeForPrincipal(_principal('org_admin')), isA<AdminShell>());
    });

    test('a parent or driver never lands on the admin screens', () {
      expect(homeForPrincipal(_principal('parent')), isNot(isA<AdminShell>()));
      expect(homeForPrincipal(_principal('driver')), isNot(isA<AdminShell>()));
    });

    test('RAAD staff roles have no mobile experience', () {
      for (final role in [
        'founder',
        'regional_manager',
        'support_staff',
        'finance_staff'
      ]) {
        expect(
            homeForPrincipal(_principal(role)), isA<UnsupportedRoleScreen>());
      }
    });

    test('a temporary password is changed first, whatever the role', () {
      expect(
          homeForPrincipal(_principal('org_admin', mustChangePassword: true)),
          isA<ChangePasswordScreen>());
    });
  });

  group('Admin data', () {
    test('parses the daily board the backend returns', () {
      final board = DailyBoard.fromJson({
        'date': '2026-10-07',
        'closures': ['Eid'],
        'uncovered_trips': 2,
        'vehicles': [
          {
            'vehicle_id': 'v1',
            'crew_gaps': 0,
            'crew': [
              {
                'staff_id': 's1',
                'staff_name': 'Hodan',
                'role_name': null,
                'is_substitute': false,
                'is_unavailable': true,
                'covered_by': null
              }
            ],
            'trips': [
              {
                'id': 't1',
                'trip_type': 'morning',
                'route_id': 'r1',
                'route_name': 'North',
                'planned_departure': '06:30:00',
                'driver_id': 'd1',
                'driver_name': 'Cabdi',
                'status': 'scheduled',
                'cancelled_reason': null,
                'uncovered_reason': 'driver_not_compliant'
              }
            ]
          }
        ]
      });
      expect(board.uncoveredTrips, 2);
      expect(board.closures, ['Eid']);
      expect(board.tripCount, 1);
      expect(board.vehicles.single.trips.single.uncoveredReason,
          'driver_not_compliant');
      expect(board.vehicles.single.crew.single.isUnavailable, isTrue);
    });

    test('parses a safety alert and reads its time as UTC', () {
      final alert = SafetyAlert.fromJson({
        'id': 'a1',
        'vehicle_id': 'v1',
        'alarm_type': 'collision',
        'is_critical': true,
        'status': 'acknowledged',
        'last_raised_at': '2026-10-07T06:20:00',
        'is_late': true,
        'occurrences': 2
      });
      expect(alert.isCritical, isTrue);
      expect(alert.isLate, isTrue);
      expect(alert.lastRaisedAt, DateTime.utc(2026, 10, 7, 6, 20).toLocal());
    });

    test('online buses keep the true total beyond the listed ones', () {
      final fleet = FleetOnline.fromJson({
        'total_online': 140,
        'vehicles': [
          {
            'vehicle_id': 'v1',
            'plate_no': 'AB-1',
            'label': null,
            'device_id': 'd',
            'is_online': true,
            'position': null
          }
        ]
      });
      expect(fleet.totalOnline, 140);
      expect(fleet.vehicles.single.displayName, 'AB-1');
    });
  });

  group('Admin overview', () {
    testWidgets('shows the figures and what needs attention', (tester) async {
      await tester.pumpWidget(testApp(const AdminShell(),
          repository: FakeRepository(), admin: _busyDay(), role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('Organization overview'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('310'), findsOneWidget);
      expect(find.text('1 open safety alert(s)'), findsOneWidget);
      expect(find.text('1 trip(s) without a driver today'), findsOneWidget);
    });

    testWidgets('a figure that could not be read is a dash, not zero',
        (tester) async {
      final admin = FakeAdminRepository()
        ..overviewData = const AdminOverview(
            vehicles: 5,
            onlineNow: null,
            tripsInProgress: 0,
            students: null,
            drivers: 2,
            routes: 1);
      await tester.pumpWidget(testApp(AdminOverviewScreen(onOpenTab: (_) {}),
          repository: FakeRepository(), admin: admin, role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('—'), findsNWidgets(2));
      expect(find.text('Nothing needs attention.'), findsOneWidget);
    });

    testWidgets('offline shows the error with a retry', (tester) async {
      final admin = FakeAdminRepository()..failWith = offline;
      await tester.pumpWidget(testApp(AdminOverviewScreen(onOpenTab: (_) {}),
          repository: FakeRepository(), admin: admin, role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('Try again'), findsOneWidget);
    });

    testWidgets('tapping an attention row opens its tab', (tester) async {
      await tester.pumpWidget(testApp(const AdminShell(),
          repository: FakeRepository(), admin: _busyDay(), role: 'org_admin'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('1 open safety alert(s)'));
      await tester.pumpAndSettle();
      expect(find.text('Safety alerts'), findsOneWidget);
      expect(find.text('SOS'), findsOneWidget);
    });
  });

  group('Admin today', () {
    testWidgets('lists each bus with its trips, driver and gaps',
        (tester) async {
      await tester.pumpWidget(testApp(const AdminTodayScreen(),
          repository: FakeRepository(), admin: _busyDay(), role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('Bus A · AB-123'), findsOneWidget);
      expect(find.text('Morning · 06:30'), findsOneWidget);
      expect(find.text('North route · Cabdi'), findsOneWidget);
      expect(find.text('North route · No driver'), findsOneWidget);
      expect(find.text('Driver is unavailable today'), findsOneWidget);
      expect(find.text('Hodan · Attendant · Substitute'), findsOneWidget);
    });

    testWidgets('no trips today', (tester) async {
      await tester.pumpWidget(testApp(const AdminTodayScreen(),
          repository: FakeRepository(),
          admin: FakeAdminRepository(),
          role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('No trips are planned today.'), findsOneWidget);
    });
  });

  group('Admin alerts', () {
    testWidgets('an open critical alert names the bus and has no action',
        (tester) async {
      await tester.pumpWidget(testApp(const AdminAlertsScreen(),
          repository: FakeRepository(), admin: _busyDay(), role: 'org_admin'));
      await tester.pumpAndSettle();

      expect(find.text('SOS'), findsOneWidget);
      expect(find.text('Bus A · AB-123'), findsOneWidget);
      expect(find.text('Critical'), findsOneWidget);
      expect(find.byType(FilledButton), findsNothing);
      expect(find.byType(OutlinedButton), findsNothing);
    });

    testWidgets('reads in Somali', (tester) async {
      await tester.pumpWidget(testApp(const AdminAlertsScreen(),
          repository: FakeRepository(),
          admin: _busyDay(),
          role: 'org_admin',
          somali: true));
      await tester.pumpAndSettle();

      expect(find.text('Digniinaha badbaadada'), findsOneWidget);
      expect(find.text('Degdeg'), findsOneWidget);
    });
  });

  group('Theme', () {
    test('light and dark use the web dashboard tokens', () {
      final light = raadTheme(Brightness.light);
      final dark = raadTheme(Brightness.dark);
      expect(light.colorScheme.primary, const Color(0xFF1E63FF));
      expect(light.scaffoldBackgroundColor, const Color(0xFFF4F6FA));
      expect(dark.colorScheme.primary, const Color(0xFF3B82F6));
      expect(dark.scaffoldBackgroundColor, const Color(0xFF090D16));
      expect(dark.colorScheme.surface, const Color(0xFF111827));
      expect(dark.colorScheme.onSurface, const Color(0xFFF8FAFC));
    });

    testWidgets('the admin screens render in dark', (tester) async {
      await tester.pumpWidget(testApp(const AdminShell(),
          repository: FakeRepository(),
          admin: _busyDay(),
          role: 'org_admin',
          dark: true));
      await tester.pumpAndSettle();

      final context = tester.element(find.text('Organization overview'));
      expect(Theme.of(context).brightness, Brightness.dark);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the parent home renders in dark', (tester) async {
      final repository = FakeRepository()..children = [child()];
      await tester.pumpWidget(testApp(const ParentHomeScreen(),
          repository: repository, dark: true));
      await tester.pumpAndSettle();

      final context = tester.element(find.byType(ParentHomeScreen));
      expect(Theme.of(context).brightness, Brightness.dark);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the account screen switches between light and dark',
        (tester) async {
      await tester.pumpWidget(testApp(const ProfileScreen(title: 'My account'),
          repository: FakeRepository(), role: 'org_admin'));
      await tester.pumpAndSettle();
      expect(find.text('Organization admin'), findsNothing,
          reason: 'the fake profile is a parent');

      await tester.scrollUntilVisible(find.text('Dark'), 200);
      await tester.tap(find.text('Dark'));
      await tester.pumpAndSettle();
      final context = tester.element(find.byType(ProfileScreen));
      expect(Theme.of(context).brightness, Brightness.dark);
    });
  });
}
