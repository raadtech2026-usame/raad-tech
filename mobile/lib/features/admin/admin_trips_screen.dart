import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 3 & 5: Trips Management, Dispatch & Real-Time Bus Search.
/// Allows the Org Admin to search trips by bus name or license plate,
/// filter by progress/schedule, and start or complete trips on the fly.
class AdminTripsScreen extends ConsumerStatefulWidget {
  const AdminTripsScreen({super.key});

  @override
  ConsumerState<AdminTripsScreen> createState() => _AdminTripsScreenState();
}

class _AdminTripsScreenState extends ConsumerState<AdminTripsScreen> {
  final _searchController = TextEditingController();
  String _statusFilter = 'all'; // all, in_progress, scheduled, completed
  String _searchQuery = '';

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    ref.invalidate(adminTripsItemsProvider);
    await ref.read(adminTripsItemsProvider.future);
  }

  Future<void> _startTrip(String tripId) async {
    final s = ref.read(stringsProvider);
    try {
      await ref.read(adminRepositoryProvider).startTrip(tripId);
      if (mounted) {
        showNotice(context, 'Safarka waa la bilaabay');
        _refresh();
      }
    } catch (err) {
      if (mounted) showNotice(context, errorMessage(err, s), isError: true);
    }
  }

  Future<void> _endTrip(String tripId) async {
    final s = ref.read(stringsProvider);
    try {
      await ref.read(adminRepositoryProvider).endTrip(tripId);
      if (mounted) {
        showNotice(context, 'Safarka waa la soo gabagabeeyay');
        _refresh();
      }
    } catch (err) {
      if (mounted) showNotice(context, errorMessage(err, s), isError: true);
    }
  }

  void _openScheduleTripModal(BuildContext context, Strings s) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => const _ScheduleTripSheet(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final tripsAsync = ref.watch(adminTripsItemsProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminTripsTitle),
        actions: adminTopActions(context, ref, onRefresh: _refresh),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_rounded),
        label: Text(s.adminScheduleTripAction),
        onPressed: () => _openScheduleTripModal(context, s),
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: Column(
          children: [
            // Top Search Bar
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: s.adminSearchBus,
                  prefixIcon: const Icon(Icons.search_rounded),
                  suffixIcon: _searchQuery.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear_rounded, size: 18),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _searchQuery = '');
                          },
                        )
                      : null,
                  filled: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
                onChanged: (val) => setState(() => _searchQuery = val.trim().toLowerCase()),
              ),
            ),

            // Status Filter Chips
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: Row(
                children: [
                  _filterChip(s.adminFilterAll, 'all'),
                  const SizedBox(width: 8),
                  _filterChip(s.adminFilterInProgress, 'in_progress'),
                  const SizedBox(width: 8),
                  _filterChip(s.adminFilterScheduled, 'scheduled'),
                  const SizedBox(width: 8),
                  _filterChip(s.adminFilterCompleted, 'completed'),
                ],
              ),
            ),
            const SizedBox(height: 4),

            // Trips List
            Expanded(
              child: tripsAsync.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (err, _) => Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(errorMessage(err, s)),
                      const SizedBox(height: 8),
                      OutlinedButton(onPressed: _refresh, child: Text(s.retry)),
                    ],
                  ),
                ),
                data: (trips) {
                  final filtered = trips.where((t) {
                    // Filter by status
                    if (_statusFilter != 'all' && t.status.toLowerCase() != _statusFilter) {
                      return false;
                    }
                    // Filter by search query (bus plate, route name, driver name)
                    if (_searchQuery.isNotEmpty) {
                      final plate = (t.vehiclePlate ?? '').toLowerCase();
                      final driver = (t.driverName ?? '').toLowerCase();
                      final route = (t.routeName ?? '').toLowerCase();
                      final matches = plate.contains(_searchQuery) ||
                          driver.contains(_searchQuery) ||
                          route.contains(_searchQuery);
                      if (!matches) return false;
                    }
                    return true;
                  }).toList();

                  if (filtered.isEmpty) {
                    return Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.directions_bus_outlined, size: 48, color: context.muted),
                          const SizedBox(height: 12),
                          Text(
                            s.emptyState,
                            style: TextStyle(color: context.muted, fontSize: 14),
                          ),
                        ],
                      ),
                    );
                  }

                  return ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 6, 16, 24),
                    itemCount: filtered.length,
                    itemBuilder: (ctx, i) {
                      final trip = filtered[i];
                      return _TripCard(
                        trip: trip,
                        onStart: () => _startTrip(trip.id),
                        onEnd: () => _endTrip(trip.id),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _filterChip(String label, String value) {
    final selected = _statusFilter == value;
    return ChoiceChip(
      label: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: selected ? FontWeight.bold : FontWeight.normal,
        ),
      ),
      selected: selected,
      onSelected: (val) {
        if (val) setState(() => _statusFilter = value);
      },
    );
  }
}

class _TripCard extends StatelessWidget {
  final AdminTripItem trip;
  final VoidCallback onStart;
  final VoidCallback onEnd;

  const _TripCard({
    required this.trip,
    required this.onStart,
    required this.onEnd,
  });

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'in_progress':
        return RaadColors.green;
      case 'completed':
        return Colors.blue;
      case 'scheduled':
        return RaadColors.amber;
      default:
        return Colors.grey;
    }
  }

  String _statusLabel(String status, Strings s) {
    switch (status.toLowerCase()) {
      case 'in_progress':
        return s.adminFilterInProgress;
      case 'completed':
        return s.adminFilterCompleted;
      case 'scheduled':
        return s.adminFilterScheduled;
      default:
        return status;
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    final color = _statusColor(trip.status);

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0.5,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.directions_bus_rounded, color: color, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    trip.vehiclePlate ?? 'Bas taargo la\'aan',
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _statusLabel(trip.status, s),
                    style: TextStyle(
                      color: color,
                      fontWeight: FontWeight.bold,
                      fontSize: 11,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Icon(Icons.alt_route_rounded, size: 15, color: context.muted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Khadka: ${trip.routeName ?? "Aan la cayimin"}',
                    style: TextStyle(fontSize: 13, color: context.muted),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Icon(Icons.person_rounded, size: 15, color: context.muted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Darawalka: ${trip.driverName ?? "Aan la qoondeen"}',
                    style: TextStyle(fontSize: 13, color: context.muted),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            if (trip.plannedDeparture != null && trip.plannedDeparture!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  Icon(Icons.schedule_rounded, size: 15, color: context.muted),
                  const SizedBox(width: 6),
                  Text(
                    'Bixitaanka: ${trip.plannedDeparture}',
                    style: TextStyle(fontSize: 12, color: context.muted),
                  ),
                ],
              ),
            ],
            const Divider(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (trip.isScheduled)
                  ElevatedButton.icon(
                    icon: const Icon(Icons.play_arrow_rounded, size: 16),
                    label: Text(s.adminStartTripAction),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: RaadColors.green,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                      minimumSize: Size.zero,
                    ),
                    onPressed: onStart,
                  ),
                if (trip.isInProgress)
                  ElevatedButton.icon(
                    icon: const Icon(Icons.stop_rounded, size: 16),
                    label: Text(s.adminEndTripAction),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: RaadColors.red,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                      minimumSize: Size.zero,
                    ),
                    onPressed: onEnd,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ScheduleTripSheet extends ConsumerStatefulWidget {
  const _ScheduleTripSheet();

  @override
  ConsumerState<_ScheduleTripSheet> createState() => _ScheduleTripSheetState();
}

class _ScheduleTripSheetState extends ConsumerState<_ScheduleTripSheet> {
  final _formKey = GlobalKey<FormState>();
  String? _selectedRouteId;
  String? _selectedVehicleId;
  String? _selectedDriverId;
  String _tripType = 'morning';
  DateTime _scheduledDate = DateTime.now();
  bool _submitting = false;

  Future<void> _submit(Strings s) async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedRouteId == null ||
        _selectedVehicleId == null ||
        _selectedDriverId == null) {
      showNotice(context, s.allFieldsRequired, isError: true);
      return;
    }

    setState(() => _submitting = true);
    final dateStr =
        '${_scheduledDate.year}-${_scheduledDate.month.toString().padLeft(2, '0')}-${_scheduledDate.day.toString().padLeft(2, '0')}';

    try {
      await ref.read(adminRepositoryProvider).scheduleTrip(
            vehicleId: _selectedVehicleId!,
            driverId: _selectedDriverId!,
            routeId: _selectedRouteId!,
            tripType: _tripType,
            scheduledDate: dateStr,
          );
      if (!mounted) return;
      Navigator.of(context).pop();
      showNotice(context, 'Safarka si guul leh ayaa loo qorsheeyay');
      ref.invalidate(adminTripsItemsProvider);
    } catch (e) {
      if (!mounted) return;
      setState(() => _submitting = false);
      showNotice(context, errorMessage(e, s), isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final theme = Theme.of(context);
    final routesAsync = ref.watch(adminRoutesProvider);
    final vehiclesAsync = ref.watch(adminVehiclesListProvider);
    final driversAsync = ref.watch(adminDriversProvider);

    return Container(
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: EdgeInsets.fromLTRB(
        20,
        16,
        20,
        MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color: Colors.grey.withValues(alpha: 0.3),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              Text(
                s.adminScheduleTripAction,
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
              ),
              const SizedBox(height: 16),

              // Route Picker
              routesAsync.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text(errorMessage(e, s)),
                data: (routes) => DropdownButtonFormField<String>(
                  decoration: InputDecoration(
                    labelText: s.adminSelectRoute,
                    prefixIcon: const Icon(Icons.alt_route_rounded),
                    filled: true,
                  ),
                  initialValue: _selectedRouteId,
                  items: [
                    for (final r in routes)
                      DropdownMenuItem(
                        value: r.id,
                        child: Text(r.name),
                      ),
                  ],
                  onChanged: (val) => setState(() => _selectedRouteId = val),
                  validator: (v) => v == null ? s.allFieldsRequired : null,
                ),
              ),
              const SizedBox(height: 12),

              // Vehicle Picker
              vehiclesAsync.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text(errorMessage(e, s)),
                data: (vehicles) => DropdownButtonFormField<String>(
                  decoration: InputDecoration(
                    labelText: s.adminSelectBus,
                    prefixIcon: const Icon(Icons.directions_bus_rounded),
                    filled: true,
                  ),
                  initialValue: _selectedVehicleId,
                  items: [
                    for (final v in vehicles)
                      DropdownMenuItem(
                        value: v.id,
                        child: Text(v.displayName),
                      ),
                  ],
                  onChanged: (val) => setState(() => _selectedVehicleId = val),
                  validator: (v) => v == null ? s.allFieldsRequired : null,
                ),
              ),
              const SizedBox(height: 12),

              // Driver Picker
              driversAsync.when(
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text(errorMessage(e, s)),
                data: (drivers) => DropdownButtonFormField<String>(
                  decoration: InputDecoration(
                    labelText: s.adminSelectDriver,
                    prefixIcon: const Icon(Icons.person_outline_rounded),
                    filled: true,
                  ),
                  initialValue: _selectedDriverId,
                  items: [
                    for (final d in drivers)
                      DropdownMenuItem(
                        value: d.id,
                        child: Text(d.fullName),
                      ),
                  ],
                  onChanged: (val) => setState(() => _selectedDriverId = val),
                  validator: (v) => v == null ? s.allFieldsRequired : null,
                ),
              ),
              const SizedBox(height: 12),

              // Trip Type (Morning / Afternoon)
              DropdownButtonFormField<String>(
                decoration: InputDecoration(
                  labelText: s.adminTripType,
                  prefixIcon: const Icon(Icons.schedule_rounded),
                  filled: true,
                ),
                initialValue: _tripType,
                items: [
                  DropdownMenuItem(
                    value: 'morning',
                    child: Text(s.adminTripTypeMorning),
                  ),
                  DropdownMenuItem(
                    value: 'afternoon',
                    child: Text(s.adminTripTypeAfternoon),
                  ),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _tripType = val);
                },
              ),
              const SizedBox(height: 12),

              // Date Picker Tile
              InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: _scheduledDate,
                    firstDate: DateTime.now().subtract(const Duration(days: 7)),
                    lastDate: DateTime.now().add(const Duration(days: 60)),
                  );
                  if (picked != null) {
                    setState(() => _scheduledDate = picked);
                  }
                },
                child: InputDecorator(
                  decoration: InputDecoration(
                    labelText: s.adminTripDate,
                    prefixIcon: const Icon(Icons.calendar_month_rounded),
                    filled: true,
                  ),
                  child: Text(
                    '${_scheduledDate.year}-${_scheduledDate.month.toString().padLeft(2, '0')}-${_scheduledDate.day.toString().padLeft(2, '0')}',
                  ),
                ),
              ),
              const SizedBox(height: 20),

              FilledButton.icon(
                icon: _submitting
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.check_rounded),
                label: Text(s.save),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                onPressed: _submitting ? null : () => _submit(s),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
