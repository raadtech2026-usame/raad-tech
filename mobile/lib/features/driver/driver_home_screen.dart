import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/network/api_exception.dart';
import 'driver_providers.dart';
import 'trip.dart';

/// Phase M2 (docs/architecture/frontend-flutter-master-roadmap.md §5): "View assigned vehicle/
/// route/students/stops; Start/End Morning Trip; Start/End Afternoon Trip." Shows every trip in
/// the driver's own organization (see `trip_repository.dart`'s own docstring for exactly why
/// "assigned to me only" filtering isn't available yet) rather than nothing — the driver can
/// still identify their own trip by route/vehicle, and the server independently enforces
/// ownership on start/end regardless of what this list shows.
class DriverHomeScreen extends ConsumerStatefulWidget {
  const DriverHomeScreen({super.key});

  @override
  ConsumerState<DriverHomeScreen> createState() => _DriverHomeScreenState();
}

class _DriverHomeScreenState extends ConsumerState<DriverHomeScreen> {
  late Future<List<Trip>> _tripsFuture;

  @override
  void initState() {
    super.initState();
    _tripsFuture = ref.read(tripRepositoryProvider).listOrganizationTrips();
  }

  void _refresh() {
    setState(() {
      _tripsFuture = ref.read(tripRepositoryProvider).listOrganizationTrips();
    });
  }

  Future<void> _startTrip(Trip trip) => _performAction(
        () => ref.read(tripRepositoryProvider).startTrip(trip.id),
      );

  Future<void> _endTrip(Trip trip) => _performAction(
        () => ref.read(tripRepositoryProvider).endTrip(trip.id),
      );

  Future<void> _performAction(Future<Trip> Function() action) async {
    try {
      await action();
      _refresh();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.message)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Trips'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: FutureBuilder<List<Trip>>(
          future: _tripsFuture,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              final message = snapshot.error is ApiException
                  ? (snapshot.error as ApiException).message
                  : 'Could not load trips. Pull down to retry.';
              return Center(child: Text(message));
            }
            final trips = snapshot.data ?? const <Trip>[];
            if (trips.isEmpty) {
              return const Center(child: Text('No trips scheduled today.'));
            }
            return ListView.builder(
              itemCount: trips.length,
              itemBuilder: (context, index) {
                final trip = trips[index];
                return ListTile(
                  title: Text('${trip.tripType} trip — ${trip.scheduledDate}'),
                  subtitle: Text('Status: ${trip.status}'),
                  trailing: trip.canStart
                      ? FilledButton(
                          onPressed: () => _startTrip(trip),
                          child: const Text('Start'),
                        )
                      : trip.canEnd
                          ? FilledButton.tonal(
                              onPressed: () => _endTrip(trip),
                              child: const Text('End'),
                            )
                          : null,
                );
              },
            );
          },
        ),
      ),
    );
  }
}
