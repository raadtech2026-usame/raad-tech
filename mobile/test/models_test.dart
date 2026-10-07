import 'package:flutter_test/flutter_test.dart';

import 'package:raad_mobile/core/data/models.dart';
import 'package:raad_mobile/core/l10n/strings.dart';
import 'package:raad_mobile/core/network/realtime_clients.dart';
import 'package:raad_mobile/core/util/format.dart';

/// The JSON here is what the backend's own tests assert it returns (ADR-0060/0061).
void main() {
  group('ChildTransport', () {
    test('parses a child on a running trip', () {
      final child = ChildTransport.fromJson({
        'student_id': 's1',
        'full_name': 'Amina',
        'status': 'active',
        'assignment': {
          'assignment_id': 'asg-s1',
          'route': {'id': 'route-1', 'name': 'North'},
          'pickup_stop': {
            'id': 'stop-1',
            'name': 'Stop 1',
            'latitude': 2.01,
            'longitude': 45.01
          },
          'dropoff_stop': {
            'id': 'stop-9',
            'name': 'Stop 9',
            'latitude': 2.04,
            'longitude': 45.04
          },
          'vehicle': {'id': 'veh-1', 'plate_no': 'AB-1234', 'label': 'Bus'},
        },
        'current_trip': {
          'id': 'trip-1',
          'trip_type': 'afternoon',
          'status': 'in_progress',
          'scheduled_date': '2026-10-01',
          'started_at': '2026-10-01T06:30:00Z',
        },
      });

      expect(child.hasAssignment, isTrue);
      expect(child.isOnTrip, isTrue);
      expect(child.vehicle!.displayName, 'Bus · AB-1234');
      expect(child.routeName, 'North');
      // Afternoon: the stop that matters is where the child gets off.
      expect(child.relevantStop!.id, 'stop-9');
    });

    test('a child with no assignment, and dangling references, do not throw',
        () {
      final unassigned = ChildTransport.fromJson({
        'student_id': 's1',
        'full_name': 'Amina',
        'status': 'active',
        'assignment': null,
        'current_trip': null,
      });
      expect(unassigned.hasAssignment, isFalse);
      expect(unassigned.isOnTrip, isFalse);
      expect(unassigned.relevantStop, isNull);

      final dangling = ChildTransport.fromJson({
        'student_id': 's1',
        'full_name': 'Amina',
        'status': 'active',
        'assignment': {
          'assignment_id': 'a',
          'route': null,
          'pickup_stop': null,
          'dropoff_stop': null,
          'vehicle': null,
        },
        'current_trip': null,
      });
      expect(dangling.hasAssignment, isTrue);
      expect(dangling.vehicle, isNull);
      expect(dangling.routeName, isNull);
    });
  });

  group('Trip', () {
    test('parses status, cancellation and riders', () {
      final trip = Trip.fromJson({
        'id': 't1',
        'trip_type': 'morning',
        'status': 'cancelled',
        'scheduled_date': '2026-10-02',
        'planned_departure': '06:30:00',
        'started_at': null,
        'ended_at': null,
        'cancelled_reason': 'Bus in the workshop',
        'route_id': 'r1',
        'route_name': 'North',
        'vehicle': {'id': 'v1', 'plate_no': 'AB-1', 'label': null},
        'is_cover': true,
        'students': [
          {'student_id': 's1', 'full_name': 'Amina'},
        ],
      });

      expect(trip.isCancelled, isTrue);
      expect(trip.isFinished, isTrue);
      expect(trip.cancelledReason, 'Bus in the workshop');
      expect(trip.isCover, isTrue);
      expect(trip.studentIds, ['s1']);
      expect(trip.scheduledDate, DateTime(2026, 10, 2));
      expect(trip.vehicle!.displayName, 'AB-1');
      expect(shortTime(trip.plannedDeparture), '06:30');
    });
  });

  group('AppNotification', () {
    AppNotification parse(String type, [Map<String, dynamic>? data]) {
      return AppNotification.fromJson({
        'id': 'n1',
        'type': type,
        'title': 'T',
        'body': 'B',
        'data': data,
        'trip_id': null,
        'status': 'unread',
        'created_at': '2026-10-02T06:00:00Z',
        'read_at': null,
      });
    }

    test('bus events are transport; office messages are not', () {
      expect(parse('trip_started').isTransport, isTrue);
      expect(parse('approaching_stop').isTransport, isTrue);
      expect(parse('system', {'kind': 'trip_cancelled'}).isTransport, isTrue);
      expect(parse('system', {'kind': 'cover_assigned'}).isTransport, isTrue);
      expect(parse('system', {'kind': 'incident_notice'}).isTransport, isFalse);
      expect(parse('system').isTransport, isFalse);
      expect(parse('subscription').isTransport, isFalse);
    });

    test('read state comes from status or read_at', () {
      expect(parse('system').isRead, isFalse);
      final read = AppNotification.fromJson({
        'id': 'n1',
        'type': 'system',
        'title': 'T',
        'body': 'B',
        'status': 'read',
        'created_at': '2026-10-02T06:00:00Z',
      });
      expect(read.isRead, isTrue);
    });
  });

  group('TrackingPosition', () {
    test('reads the WebSocket frame and the REST shape', () {
      final frame = TrackingPosition.fromJson({
        'type': 'position',
        'vehicle_id': 'v1',
        'lat': 2.04,
        'lng': 45.31,
        'speed_kph': 32,
        'event_time': '2026-10-02T06:00:00+00:00',
        'is_gps_valid': true,
      });
      expect(frame.hasFix, isTrue);
      expect(frame.lat, 2.04);

      final rest = TrackingPosition.fromJson({
        'vehicle_id': 'v1',
        'latitude': 2.04,
        'longitude': 45.31,
        'is_gps_valid': true,
      });
      expect(rest.lng, 45.31);
    });

    test('an invalid fix is not a position to draw', () {
      final noFix = TrackingPosition.fromJson({
        'vehicle_id': 'v1',
        'lat': 0.0,
        'lng': 0.0,
        'is_gps_valid': false,
      });
      expect(noFix.hasFix, isFalse);
    });
  });

  group('formatting', () {
    test('a server time without an offset is read as UTC', () {
      final bare = parseServerTime('2026-10-03T06:20:00');
      final zulu = parseServerTime('2026-10-03T06:20:00Z');
      final offset = parseServerTime('2026-10-03T09:20:00+03:00');
      expect(bare, zulu);
      expect(offset, zulu);
      expect(bare!.isUtc, isFalse);
      expect(parseServerTime(null), isNull);
      expect(parseServerTime('not a time'), isNull);
    });

    test('distance', () {
      // About 111 km per degree of latitude.
      expect(distanceMetres(2.0, 45.0, 2.001, 45.0), closeTo(111.2, 1));
      expect(friendlyDistance(304), '300 m');
      expect(friendlyDistance(1240), '1.2 km');
    });

    test('days read as today, tomorrow, yesterday, else a date', () {
      const s = Strings(false);
      final now = DateTime(2026, 10, 2, 9);
      expect(friendlyDay(DateTime(2026, 10, 2), s, now: now), 'Today');
      expect(friendlyDay(DateTime(2026, 10, 3), s, now: now), 'Tomorrow');
      expect(friendlyDay(DateTime(2026, 10, 1), s, now: now), 'Yesterday');
      expect(friendlyDay(DateTime(2026, 9, 5), s, now: now), '05/09/2026');
      expect(isoDate(DateTime(2026, 9, 5)), '2026-09-05');
    });

    test('Somali and English both have every trip status', () {
      for (final status in [
        'scheduled',
        'in_progress',
        'completed',
        'cancelled'
      ]) {
        expect(const Strings(true).tripStatus(status), isNot(status));
        expect(const Strings(false).tripStatus(status), isNot(status));
      }
    });
  });
}
