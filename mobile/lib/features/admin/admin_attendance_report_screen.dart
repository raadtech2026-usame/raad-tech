import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

class AdminAttendanceReportScreen extends ConsumerStatefulWidget {
  const AdminAttendanceReportScreen({super.key});

  @override
  ConsumerState<AdminAttendanceReportScreen> createState() =>
      _AdminAttendanceReportScreenState();
}

class _AdminAttendanceReportScreenState
    extends ConsumerState<AdminAttendanceReportScreen> {
  String? _selectedVehicleId; // 'all' or vehicle id
  String _selectedDate = isoDate(DateTime.now());
  String _statusFilter = 'all'; // 'all', 'present', 'absent'
  String _searchQuery = '';
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: now,
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year + 1),
    );
    if (picked != null) {
      setState(() => _selectedDate = isoDate(picked));
    }
  }

  AdminAttendanceQuery get _query => AdminAttendanceQuery(
        vehicleId: _selectedVehicleId == 'all' ? null : _selectedVehicleId,
        date: _selectedDate == 'all' ? null : _selectedDate,
        status: _statusFilter == 'all' ? null : _statusFilter,
      );

  void _refresh() {
    ref.invalidate(adminAttendanceReportProvider(_query));
    ref.invalidate(adminVehiclesListProvider);
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final vehiclesAsync = ref.watch(adminVehiclesListProvider);
    final reportAsync = ref.watch(adminAttendanceReportProvider(_query));
    final todayStr = isoDate(DateTime.now());
    final yesterdayStr =
        isoDate(DateTime.now().subtract(const Duration(days: 1)));

    return Scaffold(
      appBar: AppBar(
        title: Text(s.attendanceReportTitle),
        actions: adminTopActions(context, ref, onRefresh: _refresh),
      ),
      body: RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            // Bus Filter Dropdown
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerLow,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: Theme.of(context)
                      .colorScheme
                      .outlineVariant
                      .withValues(alpha: 0.5),
                ),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  isExpanded: true,
                  value: _selectedVehicleId ?? 'all',
                  icon: const Icon(Icons.keyboard_arrow_down_rounded),
                  items: [
                    DropdownMenuItem(
                      value: 'all',
                      child: Row(
                        children: [
                          const Icon(Icons.directions_bus_rounded,
                              size: 20, color: RaadColors.brandPrimary),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              s.adminFilterAllBuses,
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600, fontSize: 13.5),
                            ),
                          ),
                        ],
                      ),
                    ),
                    for (final v in (vehiclesAsync.valueOrNull ?? <AdminVehicle>[]))
                      DropdownMenuItem(
                        value: v.id,
                        child: Row(
                          children: [
                            const Icon(Icons.directions_bus_outlined,
                                size: 20, color: Colors.blueGrey),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                v.displayName,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600, fontSize: 13.5),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                  onChanged: (val) {
                    setState(() => _selectedVehicleId = val);
                  },
                ),
              ),
            ),

            // Date Selection Row
            Row(
              children: [
                Expanded(
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: [
                        FilterChip(
                          selected: _selectedDate == todayStr,
                          label: const Text('Maanta'),
                          onSelected: (_) =>
                              setState(() => _selectedDate = todayStr),
                        ),
                        const SizedBox(width: 6),
                        FilterChip(
                          selected: _selectedDate == yesterdayStr,
                          label: const Text('Shalay'),
                          onSelected: (_) =>
                              setState(() => _selectedDate = yesterdayStr),
                        ),
                        const SizedBox(width: 6),
                        FilterChip(
                          selected: _selectedDate == 'all',
                          label: Text(s.adminFilterAll),
                          onSelected: (_) =>
                              setState(() => _selectedDate = 'all'),
                        ),
                      ],
                    ),
                  ),
                ),
                IconButton.filledTonal(
                  icon: const Icon(Icons.calendar_month_rounded, size: 20),
                  tooltip: s.filterByDate,
                  onPressed: _pickDate,
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Student Search Input
            TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: s.filterByStudent,
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
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
              ),
              onChanged: (val) => setState(() => _searchQuery = val.trim().toLowerCase()),
            ),
            const SizedBox(height: 14),

            // Report Async Body
            reportAsync.when(
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 40),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (err, _) => SectionCard(
                child: Row(
                  children: [
                    const Icon(Icons.error_outline_rounded,
                        color: RaadColors.red),
                    const SizedBox(width: 12),
                    Expanded(child: Text(errorMessage(err, s))),
                    OutlinedButton(onPressed: _refresh, child: Text(s.retry)),
                  ],
                ),
              ),
              data: (report) {
                final filtered = report.records.where((r) {
                  if (_searchQuery.isNotEmpty) {
                    final name = r.studentName.toLowerCase();
                    final route = (r.routeName ?? '').toLowerCase();
                    if (!name.contains(_searchQuery) &&
                        !route.contains(_searchQuery)) {
                      return false;
                    }
                  }
                  return true;
                }).toList();

                final total = report.summary.total;
                final present = report.summary.present;
                final absent = report.summary.absent;
                final rate = report.summary.rate;

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // KPI Strip
                    Container(
                      margin: const EdgeInsets.only(bottom: 12),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerLowest,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: Theme.of(context)
                              .colorScheme
                              .outlineVariant
                              .withValues(alpha: 0.35),
                        ),
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceAround,
                        children: [
                          _AttendanceKpiPill(
                            label: 'Arday',
                            value: '$total',
                            color: RaadColors.brandPrimary,
                          ),
                          _AttendanceKpiPill(
                            label: s.present,
                            value: '$present',
                            color: RaadColors.green,
                          ),
                          _AttendanceKpiPill(
                            label: s.absent,
                            value: '$absent',
                            color: RaadColors.red,
                          ),
                          _AttendanceKpiPill(
                            label: s.attendanceRate,
                            value: '$rate%',
                            color: Colors.blue,
                          ),
                        ],
                      ),
                    ),

                    // Status Filter Chips
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          FilterChip(
                            selected: _statusFilter == 'all',
                            label: Text('${s.adminFilterAll} ($total)'),
                            onSelected: (_) =>
                                setState(() => _statusFilter = 'all'),
                          ),
                          const SizedBox(width: 6),
                          FilterChip(
                            selected: _statusFilter == 'present',
                            label: Text('${s.present} ($present)'),
                            onSelected: (_) =>
                                setState(() => _statusFilter = 'present'),
                          ),
                          const SizedBox(width: 6),
                          FilterChip(
                            selected: _statusFilter == 'absent',
                            label: Text('${s.absent} ($absent)'),
                            onSelected: (_) =>
                                setState(() => _statusFilter = 'absent'),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Records List
                    if (filtered.isEmpty)
                      SectionCard(
                        padding: const EdgeInsets.symmetric(
                            vertical: 36, horizontal: 16),
                        child: Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.fact_check_outlined,
                                  size: 44, color: context.muted),
                              const SizedBox(height: 10),
                              Text(
                                'Wax xog xaadirin ah lama helin',
                                style: TextStyle(
                                    fontSize: 14, color: context.muted),
                              ),
                            ],
                          ),
                        ),
                      )
                    else
                      for (final record in filtered)
                        _AttendanceCard(record: record),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _AttendanceKpiPill extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _AttendanceKpiPill({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value,
          style: TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 15,
            color: color,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: TextStyle(fontSize: 11, color: context.muted),
        ),
      ],
    );
  }
}

class _AttendanceCard extends StatelessWidget {
  final AdminAttendanceRecord record;

  const _AttendanceCard({required this.record});

  @override
  Widget build(BuildContext context) {
    final isPresent = record.isPresent;
    final statusColor = isPresent ? RaadColors.green : RaadColors.red;
    final statusLabel = isPresent ? 'IMAADAY' : 'MAQAN';

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      elevation: 0.5,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.4),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: statusColor.withValues(alpha: 0.12),
              child: Icon(
                isPresent
                    ? Icons.check_circle_rounded
                    : Icons.cancel_outlined,
                size: 20,
                color: statusColor,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    record.studentName,
                    style: const TextStyle(
                      fontSize: 14.5,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      if (record.routeName != null) ...[
                        Icon(Icons.alt_route_rounded,
                            size: 14, color: context.muted),
                        const SizedBox(width: 4),
                        Text(
                          record.routeName!,
                          style: TextStyle(fontSize: 12, color: context.muted),
                        ),
                        const SizedBox(width: 10),
                      ],
                      Icon(Icons.calendar_today_rounded,
                          size: 13, color: context.muted),
                      const SizedBox(width: 4),
                      Text(
                        record.attendanceDate,
                        style: TextStyle(fontSize: 12, color: context.muted),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: statusColor.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                statusLabel,
                style: TextStyle(
                  color: statusColor,
                  fontWeight: FontWeight.bold,
                  fontSize: 11,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
