import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:raad_mobile/core/data/models.dart';
import 'package:raad_mobile/core/l10n/strings.dart';
import 'package:raad_mobile/features/auth/change_password_screen.dart';
import 'package:raad_mobile/features/auth/login_screen.dart';
import 'package:raad_mobile/features/common/notifications_screen.dart';
import 'package:raad_mobile/features/driver/driver_screens.dart';
import 'package:raad_mobile/features/driver/driver_self_service.dart';
import 'package:raad_mobile/features/parent/parent_screens.dart';

import 'support.dart';

void main() {
  group('Login', () {
    testWidgets('is in Somali by default and switches to English',
        (tester) async {
      await tester.pumpWidget(
          const ProviderScope(child: MaterialApp(home: LoginScreen())));

      expect(find.text('RAAD'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Gal'), findsOneWidget);

      await tester.tap(find.text('English'));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(FilledButton, 'Sign in'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Email or phone number'),
          findsOneWidget);
    });

    testWidgets('hides the password', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [languageProvider.overrideWith((ref) => 'en')],
          child: const MaterialApp(home: LoginScreen()),
        ),
      );
      final field =
          tester.widget<TextField>(find.widgetWithText(TextField, 'Password'));
      expect(field.obscureText, isTrue);
    });

    testWidgets('says when the session expired', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [languageProvider.overrideWith((ref) => 'en')],
          child: const MaterialApp(home: LoginScreen(sessionExpired: true)),
        ),
      );
      expect(find.textContaining('session expired'), findsOneWidget);
    });
  });

  group('Change password', () {
    testWidgets('refuses a short password and two that differ', (tester) async {
      await tester.pumpWidget(
        testApp(const ChangePasswordScreen(), repository: FakeRepository()),
      );
      await tester.enterText(find.byType(TextField).first, 'short');
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pump();
      expect(find.text('Use at least 8 characters.'), findsOneWidget);

      await tester.enterText(find.byType(TextField).first, 'long-enough-1');
      await tester.enterText(find.byType(TextField).last, 'long-enough-2');
      await tester.tap(find.widgetWithText(FilledButton, 'Save'));
      await tester.pump();
      expect(find.text('The two passwords do not match.'), findsOneWidget);
    });
  });

  group('Parent home', () {
    testWidgets(
        'shows the child, the bus, the stops and no tracking outside a trip',
        (tester) async {
      final repository = FakeRepository()
        ..children = [child()]
        ..trips = [trip()];
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(find.text('Amina'), findsOneWidget);
      expect(find.text('Bus 1 · AB-1234'), findsOneWidget);
      expect(find.text('Bakaaraha'), findsOneWidget);
      expect(find.text('School gate'), findsOneWidget);
      expect(find.text('The bus is not on a trip now'), findsOneWidget);
      // Live GPS is offered only during a trip (`.claude/rules/flutter.md` #4).
      expect(find.text('Track the bus'), findsNothing);
      expect(find.text('Scheduled'), findsOneWidget);
    });

    testWidgets('offers tracking while the bus is on a trip', (tester) async {
      final repository = FakeRepository()
        ..children = [child(onTrip: true)]
        ..trips = [trip(status: 'in_progress')];
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(
          find.widgetWithText(FilledButton, 'Track the bus'), findsOneWidget);
      expect(find.text('On trip'), findsWidgets);
    });

    testWidgets('a cancelled trip shows its reason', (tester) async {
      final repository = FakeRepository()
        ..children = [child()]
        ..trips = [
          trip(status: 'cancelled', cancelledReason: 'Bus in the workshop')
        ];
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(find.text('Cancelled'), findsOneWidget);
      expect(find.text('Reason: Bus in the workshop'), findsOneWidget);
    });

    testWidgets('two children are selected separately', (tester) async {
      final repository = FakeRepository()
        ..children = [child(), child(id: 's2', name: 'Bilal', assigned: false)]
        ..trips = [trip()];
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(ChoiceChip, 'Amina'), findsOneWidget);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Bilal'));
      await tester.pumpAndSettle();

      expect(find.text('This child has not been assigned to a bus yet.'),
          findsOneWidget);
      expect(find.text('Bakaaraha'), findsNothing);
    });

    testWidgets('no children, offline, and a retry', (tester) async {
      final repository = FakeRepository()..failWith = offline;
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(find.textContaining('Could not reach the RAAD server'),
          findsOneWidget);

      repository.failWith = null;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.textContaining('No children are linked'), findsOneWidget);
    });

    testWidgets('no camera button without a grant', (tester) async {
      final repository = FakeRepository()..children = [child()];
      await tester.pumpWidget(
          testApp(const ParentHomeScreen(), repository: repository));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).first, const Offset(0, -600));
      await tester.pumpAndSettle();

      expect(find.text('Watch the bus camera'), findsNothing);
    });

    testWidgets('the camera button appears with a grant', (tester) async {
      final repository = FakeRepository()..children = [child()];
      await tester.pumpWidget(
        testApp(const ParentHomeScreen(),
            repository: repository, videoAccess: true),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Watch the bus camera'), 200);

      expect(find.text('Watch the bus camera'), findsOneWidget);
    });

    testWidgets('reads in Somali', (tester) async {
      final repository = FakeRepository()
        ..children = [child()]
        ..trips = [trip()];
      await tester.pumpWidget(
        testApp(const ParentHomeScreen(), repository: repository, somali: true),
      );
      await tester.pumpAndSettle();

      expect(find.text('Carruurtayda'), findsOneWidget);
      expect(find.text('Goobta qaadista'), findsOneWidget);
    });
  });

  group('Parent history', () {
    testWidgets('lists past trips and says what it cannot know',
        (tester) async {
      final repository = FakeRepository()
        ..children = [child()]
        ..trips = [
          trip(
              id: 'old',
              status: 'completed',
              day: today.subtract(const Duration(days: 3))),
          trip(id: 'future', day: today.add(const Duration(days: 2))),
        ];
      await tester.pumpWidget(
          testApp(const ParentHistoryScreen(), repository: repository));
      await tester.pumpAndSettle();

      expect(find.text('Completed'), findsOneWidget);
      expect(find.text('Scheduled'), findsNothing);
      expect(find.textContaining('does not record whether a child boarded'),
          findsOneWidget);
    });
  });

  group('Notifications', () {
    AppNotification notification(String id, String type,
        {String? kind, bool read = false}) {
      return AppNotification(
        id: id,
        type: type,
        title: 'Server title $id',
        body: 'Server body $id',
        kind: kind,
        createdAt: DateTime.now(),
        isRead: read,
      );
    }

    testWidgets('bus messages and school messages are separate tabs',
        (tester) async {
      final repository = FakeRepository()
        ..notificationList = [
          notification('1', 'approaching_stop'),
          notification('2', 'system'),
        ];
      await tester.pumpWidget(
        testApp(const NotificationsScreen(splitByKind: true),
            repository: repository),
      );
      await tester.pumpAndSettle();

      expect(find.text('The bus is approaching'), findsOneWidget);
      expect(find.text('Server title 2'), findsNothing);

      await tester.tap(find.text('School'));
      await tester.pumpAndSettle();

      // The office's own words are shown as written.
      expect(find.text('Server title 2'), findsOneWidget);
      expect(find.text('Server body 2'), findsOneWidget);
    });

    testWidgets('opening an unread notification marks it read', (tester) async {
      final repository = FakeRepository()
        ..notificationList = [notification('7', 'trip_started')];
      await tester.pumpWidget(
        testApp(const NotificationsScreen(splitByKind: false),
            repository: repository),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('The bus trip has started'));
      await tester.pumpAndSettle();

      expect(repository.markedRead, ['7']);
    });

    testWidgets('known bus events read in Somali', (tester) async {
      final repository = FakeRepository()
        ..notificationList = [notification('1', 'approaching_stop')];
      await tester.pumpWidget(
        testApp(
          const NotificationsScreen(splitByKind: false),
          repository: repository,
          somali: true,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Basku wuu soo dhow yahay'), findsOneWidget);
    });
  });

  group('Driver today', () {
    testWidgets('starts a scheduled trip after confirmation', (tester) async {
      final repository = FakeRepository()..trips = [trip()];
      await tester.pumpWidget(
        testApp(const DriverTodayScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Start trip'));
      await tester.pumpAndSettle();
      expect(repository.started, isEmpty);

      await tester.tap(find.widgetWithText(FilledButton, 'Confirm'));
      await tester.pumpAndSettle();
      expect(repository.started, ['trip-1']);
    });

    testWidgets('ends a running trip, and cancelling the dialog does nothing',
        (tester) async {
      final repository = FakeRepository()
        ..trips = [trip(status: 'in_progress')];
      await tester.pumpWidget(
        testApp(const DriverTodayScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'End trip'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(repository.ended, isEmpty);

      await tester.tap(find.widgetWithText(FilledButton, 'End trip'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Confirm'));
      await tester.pumpAndSettle();
      expect(repository.ended, ['trip-1']);
    });

    testWidgets('a cancelled trip has no action and shows why', (tester) async {
      final repository = FakeRepository()
        ..trips = [trip(status: 'cancelled', cancelledReason: 'School closed')];
      await tester.pumpWidget(
        testApp(const DriverTodayScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      expect(find.text('Reason: School closed'), findsOneWidget);
      expect(find.text('Start trip'), findsNothing);
      expect(find.text('End trip'), findsNothing);
    });

    testWidgets('a cover trip is marked', (tester) async {
      final repository = FakeRepository()..trips = [trip(isCover: true)];
      await tester.pumpWidget(
        testApp(const DriverTodayScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      expect(find.text('Cover'), findsOneWidget);
    });

    testWidgets('no trips today', (tester) async {
      await tester.pumpWidget(
        testApp(const DriverTodayScreen(),
            repository: FakeRepository(), role: 'driver'),
      );
      await tester.pumpAndSettle();

      expect(find.text('No trips today'), findsOneWidget);
    });
  });

  group('Driver incidents', () {
    testWidgets('a report needs a title, then is sent', (tester) async {
      final repository = FakeRepository();
      await tester.pumpWidget(
        testApp(const ReportIncidentScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Send'));
      await tester.pump();
      expect(find.text('Write at least 3 characters.'), findsOneWidget);
      expect(repository.reportedIncidents, isEmpty);

      await tester.enterText(
          find.widgetWithText(TextField, 'What happened?'), 'Flat tyre');
      await tester.tap(find.widgetWithText(FilledButton, 'Send'));
      await tester.pumpAndSettle();

      expect(repository.reportedIncidents.single['title'], 'Flat tyre');
      expect(repository.reportedIncidents.single['category'], 'delay');
    });

    testWidgets('own reports show their status', (tester) async {
      final repository = FakeRepository()
        ..incidents = [
          IncidentReport(
            id: 'i1',
            category: 'breakdown',
            severity: 'high',
            status: 'investigating',
            occurredAt: DateTime.now(),
            title: 'Flat tyre near Stop 2',
          ),
        ];
      await tester.pumpWidget(
        testApp(const IncidentsScreen(),
            repository: repository, role: 'driver'),
      );
      await tester.pumpAndSettle();

      expect(find.text('Flat tyre near Stop 2'), findsOneWidget);
      expect(find.text('Being looked into'), findsOneWidget);
    });
  });
}
