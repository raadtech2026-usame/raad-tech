import 'dart:math' as math;

import '../l10n/strings.dart';

/// `2026-10-02` for query strings and request bodies.
String isoDate(DateTime day) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${day.year}-${two(day.month)}-${two(day.day)}';
}

DateTime dateOnly(DateTime moment) =>
    DateTime(moment.year, moment.month, moment.day);

/// "Today", "Tomorrow", "Yesterday", otherwise `02/10/2026`.
String friendlyDay(DateTime day, Strings s, {DateTime? now}) {
  final today = dateOnly(now ?? DateTime.now());
  final difference = dateOnly(day).difference(today).inDays;
  if (difference == 0) return s.today;
  if (difference == 1) return s.tomorrow;
  if (difference == -1) return s.yesterday;
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(day.day)}/${two(day.month)}/${day.year}';
}

String clock(DateTime moment) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(moment.hour)}:${two(moment.minute)}';
}

/// `06:30:00` from the API becomes `06:30`.
String? shortTime(String? value) {
  if (value == null || value.length < 5) return value;
  return value.substring(0, 5);
}

String friendlyMoment(DateTime moment, Strings s) =>
    '${friendlyDay(moment, s)} ${clock(moment)}';

/// Great-circle distance in metres between two points (haversine).
double distanceMetres(double lat1, double lng1, double lat2, double lng2) {
  const earthRadius = 6371000.0;
  double rad(double degrees) => degrees * math.pi / 180;
  final dLat = rad(lat2 - lat1);
  final dLng = rad(lng2 - lng1);
  final a = math.pow(math.sin(dLat / 2), 2) +
      math.cos(rad(lat1)) *
          math.cos(rad(lat2)) *
          math.pow(math.sin(dLng / 2), 2);
  return 2 * earthRadius * math.asin(math.min(1.0, math.sqrt(a)));
}

/// `350 m`, `1.2 km`.
String friendlyDistance(double metres) {
  if (metres < 1000) return '${(metres / 10).round() * 10} m';
  return '${(metres / 1000).toStringAsFixed(1)} km';
}
