import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 4: Routes & Stops Management.
/// Allows the Org Admin to create routes and add stops with geographic coordinates.
class AdminRoutesScreen extends ConsumerStatefulWidget {
  const AdminRoutesScreen({super.key});

  @override
  ConsumerState<AdminRoutesScreen> createState() => _AdminRoutesScreenState();
}

class _AdminRoutesScreenState extends ConsumerState<AdminRoutesScreen> {
  Future<void> _refresh() async {
    ref.invalidate(adminRoutesProvider);
    await ref.read(adminRoutesProvider.future);
  }

  void _showCreateRouteSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => const _CreateRouteSheet(),
    ).then((_) => _refresh());
  }

  void _showAddStopSheet(AdminRoute route) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _AddStopSheet(route: route),
    ).then((_) => _refresh());
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final routesAsync = ref.watch(adminRoutesProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminRoutesManagementTitle),
        actions: adminTopActions(context, ref, onRefresh: _refresh),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_road_rounded),
        label: Text(s.adminCreateNewRoute),
        onPressed: _showCreateRouteSheet,
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: routesAsync.when(
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
          data: (routes) {
            if (routes.isEmpty) {
              return Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.alt_route_rounded, size: 48, color: context.muted),
                    const SizedBox(height: 12),
                    Text(
                      s.emptyState,
                      style: TextStyle(color: context.muted, fontSize: 14),
                    ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      icon: const Icon(Icons.add_rounded),
                      label: Text(s.adminCreateNewRoute),
                      onPressed: _showCreateRouteSheet,
                    ),
                  ],
                ),
              );
            }

            return ListView.builder(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
              itemCount: routes.length,
              itemBuilder: (ctx, i) {
                final route = routes[i];
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
                            Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Theme.of(context).primaryColor.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(
                                Icons.alt_route_rounded,
                                color: Theme.of(context).primaryColor,
                                size: 22,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    route.name,
                                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                                  ),
                                  if (route.code != null && route.code!.isNotEmpty)
                                    Text(
                                      'Code: ${route.code}',
                                      style: TextStyle(fontSize: 12, color: context.muted),
                                    ),
                                ],
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                              decoration: BoxDecoration(
                                color: Colors.blue.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Text(
                                '${route.stopCount} Hakad',
                                style: const TextStyle(
                                  color: Colors.blue,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const Divider(height: 20),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            OutlinedButton.icon(
                              icon: const Icon(Icons.add_location_alt_outlined, size: 16),
                              label: Text(s.adminAddStopTitle, style: const TextStyle(fontSize: 12)),
                              style: OutlinedButton.styleFrom(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                                minimumSize: Size.zero,
                              ),
                              onPressed: () => _showAddStopSheet(route),
                            ),
                          ],
                        ),
                      ],
                    ),
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

class _CreateRouteSheet extends ConsumerStatefulWidget {
  const _CreateRouteSheet();

  @override
  ConsumerState<_CreateRouteSheet> createState() => _CreateRouteSheetState();
}

class _CreateRouteSheetState extends ConsumerState<_CreateRouteSheet> {
  final _nameController = TextEditingController();
  final _codeController = TextEditingController();
  final _descController = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _codeController.dispose();
    _descController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      showNotice(context, 'Fadlan gali magaca khadka', isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).createRoute(
        name: name,
        code: _codeController.text.trim(),
        description: _descController.text.trim(),
      );
      if (mounted) {
        showNotice(context, 'Khadka si guul leh ayaa loo abuuray');
        Navigator.of(context).pop();
      }
    } catch (err) {
      if (mounted) showNotice(context, errorMessage(err, s), isError: true);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);

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
                Text(
                  s.adminCreateNewRoute,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                IconButton(
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const Divider(),
            const SizedBox(height: 8),

            TextField(
              controller: _nameController,
              decoration: InputDecoration(
                labelText: s.adminRouteNameLabel,
                prefixIcon: const Icon(Icons.edit_road_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            TextField(
              controller: _codeController,
              decoration: InputDecoration(
                labelText: s.adminRouteCodeLabel,
                prefixIcon: const Icon(Icons.tag_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            TextField(
              controller: _descController,
              maxLines: 2,
              decoration: InputDecoration(
                labelText: s.adminNotes,
                prefixIcon: const Icon(Icons.description_outlined),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 20),

            ElevatedButton(
              onPressed: _submitting ? null : _submit,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(s.save),
            ),
          ],
        ),
      ),
    );
  }
}

class _AddStopSheet extends ConsumerStatefulWidget {
  final AdminRoute route;
  const _AddStopSheet({required this.route});

  @override
  ConsumerState<_AddStopSheet> createState() => _AddStopSheetState();
}

class _AddStopSheetState extends ConsumerState<_AddStopSheet> {
  final _nameController = TextEditingController();
  final _latController = TextEditingController(text: '2.0469');
  final _lngController = TextEditingController(text: '45.3182');
  final _radiusController = TextEditingController(text: '100');
  final _seqController = TextEditingController();
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _seqController.text = '${widget.route.stopCount + 1}';
  }

  @override
  void dispose() {
    _nameController.dispose();
    _latController.dispose();
    _lngController.dispose();
    _radiusController.dispose();
    _seqController.dispose();
    super.dispose();
  }

  void _autofillBusPosition(Strings s) {
    final fleet = ref.read(adminFleetOnlineProvider).valueOrNull;
    if (fleet == null || fleet.vehicles.isEmpty) {
      showNotice(context, s.adminNoBusesOnRoad, isError: true);
      return;
    }

    final vehicleWithPos = fleet.vehicles.firstWhere(
      (v) => v.position != null,
      orElse: () => fleet.vehicles.first,
    );

    if (vehicleWithPos.position != null) {
      setState(() {
        _latController.text = vehicleWithPos.position!.latitude.toStringAsFixed(6);
        _lngController.text = vehicleWithPos.position!.longitude.toStringAsFixed(6);
      });
      showNotice(context, '${s.adminFetchBusGps}: ${vehicleWithPos.displayName}');
    } else {
      showNotice(context, 'Ma jiro bas GPS live ah soo diraya hadda', isError: true);
    }
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      showNotice(context, 'Fadlan gali magaca hakadka', isError: true);
      return;
    }
    final lat = double.tryParse(_latController.text.trim());
    final lng = double.tryParse(_lngController.text.trim());
    if (lat == null || lng == null) {
      showNotice(context, 'Coordinates qalad ah', isError: true);
      return;
    }
    final seq = int.tryParse(_seqController.text.trim()) ?? (widget.route.stopCount + 1);
    final radius = int.tryParse(_radiusController.text.trim()) ?? 100;

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).addStopToRoute(
        routeId: widget.route.id,
        name: name,
        latitude: lat,
        longitude: lng,
        sequence: seq,
        geofenceRadiusM: radius,
      );
      if (mounted) {
        showNotice(context, 'Hakadka si guul leh ayaa loogu daray khadka');
        Navigator.of(context).pop();
      }
    } catch (err) {
      if (mounted) showNotice(context, errorMessage(err, s), isError: true);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);

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
                    '${s.adminAddStopTitle} (${widget.route.name})',
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                    overflow: TextOverflow.ellipsis,
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

            TextField(
              controller: _nameController,
              decoration: InputDecoration(
                labelText: s.adminStopNameLabel,
                prefixIcon: const Icon(Icons.location_city_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Autofill button
            OutlinedButton.icon(
              icon: const Icon(Icons.my_location_rounded, size: 18),
              label: Text(s.adminFetchBusGps),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 10),
              ),
              onPressed: () => _autofillBusPosition(s),
            ),
            const SizedBox(height: 10),

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

            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _radiusController,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: s.adminGeofenceRadius,
                      prefixIcon: const Icon(Icons.radio_button_checked_rounded),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _seqController,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: s.adminSequence,
                      prefixIcon: const Icon(Icons.format_list_numbered_rounded),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),

            ElevatedButton(
              onPressed: _submitting ? null : _submit,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(s.save),
            ),
          ],
        ),
      ),
    );
  }
}
