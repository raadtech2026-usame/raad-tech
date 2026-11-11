import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 4 & 5: Drivers, Staff & Bus Crew Assignment.
/// Allows the Org Admin to add drivers and attendants,
/// and pair them to a specific vehicle fleet.
class AdminStaffScreen extends ConsumerStatefulWidget {
  const AdminStaffScreen({super.key});

  @override
  ConsumerState<AdminStaffScreen> createState() => _AdminStaffScreenState();
}

class _AdminStaffScreenState extends ConsumerState<AdminStaffScreen> {
  Future<void> _refresh() async {
    ref.invalidate(adminStaffMembersProvider);
    ref.invalidate(adminVehiclesListProvider);
    await ref.read(adminStaffMembersProvider.future);
  }

  void _showAddStaffSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => const _AddStaffSheet(),
    ).then((_) => _refresh());
  }

  void _showAssignCrewSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => const _AssignCrewSheet(),
    ).then((_) => _refresh());
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final staffAsync = ref.watch(adminStaffMembersProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminStaffManagementTitle),
        actions: adminTopActions(context, ref, onRefresh: _refresh),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.person_add_rounded),
        label: Text(s.adminCreateStaffMember),
        onPressed: _showAddStaffSheet,
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
          children: [
            // Quick Action Card: Assign Crew to Bus
            Card(
              elevation: 0.5,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              color: Theme.of(context).primaryColor.withValues(alpha: 0.06),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: Theme.of(context).primaryColor,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Icon(Icons.link_rounded, color: Colors.white, size: 22),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            s.adminAssignCrewToBus,
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Xir darawalka iyo kalkaaliyaha baska uu kaxaynayo',
                            style: TextStyle(fontSize: 12, color: context.muted),
                          ),
                        ],
                      ),
                    ),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        minimumSize: Size.zero,
                      ),
                      onPressed: _showAssignCrewSheet,
                      child: const Text('Qoondee', style: TextStyle(fontSize: 12)),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Staff List Section
            staffAsync.when(
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 36),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (err, _) => SectionCard(
                child: Text(errorMessage(err, s)),
              ),
              data: (staffMembers) {
                if (staffMembers.isEmpty) {
                  return SectionCard(
                    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.badge_outlined, size: 48, color: context.muted),
                          const SizedBox(height: 12),
                          Text(
                            s.emptyState,
                            style: TextStyle(color: context.muted, fontSize: 14),
                          ),
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            icon: const Icon(Icons.person_add_rounded),
                            label: Text(s.adminCreateStaffMember),
                            onPressed: _showAddStaffSheet,
                          ),
                        ],
                      ),
                    ),
                  );
                }

                return Column(
                  children: [
                    for (final member in staffMembers)
                      _StaffCard(member: member),
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

class _StaffCard extends StatelessWidget {
  final AdminStaff member;
  const _StaffCard({required this.member});

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    final isDriver = member.role.toLowerCase() == 'driver';
    final roleName = isDriver ? s.adminStaffRoleDriver : s.adminStaffRoleAttendant;
    final roleColor = isDriver ? Colors.blue : Colors.purple;

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0.5,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: roleColor.withValues(alpha: 0.12),
              child: Icon(
                isDriver ? Icons.drive_eta_rounded : Icons.supervised_user_circle_rounded,
                color: roleColor,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          member.fullName,
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: roleColor.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          roleName,
                          style: TextStyle(
                            color: roleColor,
                            fontWeight: FontWeight.bold,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Icon(Icons.phone_rounded, size: 14, color: context.muted),
                      const SizedBox(width: 4),
                      Text(
                        member.phone,
                        style: TextStyle(fontSize: 12.5, color: context.muted),
                      ),
                      if (member.licenseNo != null && member.licenseNo!.isNotEmpty) ...[
                        const SizedBox(width: 12),
                        Icon(Icons.badge_outlined, size: 14, color: context.muted),
                        const SizedBox(width: 4),
                        Text(
                          'Lic: ${member.licenseNo}',
                          style: TextStyle(fontSize: 12, color: context.muted),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AddStaffSheet extends ConsumerStatefulWidget {
  const _AddStaffSheet();

  @override
  ConsumerState<_AddStaffSheet> createState() => _AddStaffSheetState();
}

class _AddStaffSheetState extends ConsumerState<_AddStaffSheet> {
  final _nameController = TextEditingController();
  final _phoneController = TextEditingController();
  final _licenseController = TextEditingController();
  String _role = 'driver'; // driver or attendant
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    _licenseController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    final name = _nameController.text.trim();
    final phone = _phoneController.text.trim();
    if (name.isEmpty || phone.isEmpty) {
      showNotice(context, 'Fadlan gali magaca iyo taleefanka', isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).createStaff(
        fullName: name,
        phone: phone,
        role: _role,
        licenseNo: _licenseController.text.trim(),
      );
      if (mounted) {
        showNotice(context, 'Shaqaalaha si guul leh ayaa loo diiwaangeliyay');
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
                  s.adminCreateStaffMember,
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
              decoration: const InputDecoration(
                labelText: 'Magaca buuxa',
                prefixIcon: Icon(Icons.person_outline_rounded),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            TextField(
              controller: _phoneController,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                labelText: 'Lambarka taleefanka',
                prefixIcon: Icon(Icons.phone_outlined),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            DropdownButtonFormField<String>(
              value: _role,
              decoration: const InputDecoration(
                labelText: 'Doorka (Role)',
                prefixIcon: Icon(Icons.badge_outlined),
                border: OutlineInputBorder(),
              ),
              items: [
                DropdownMenuItem(value: 'driver', child: Text(s.adminStaffRoleDriver)),
                DropdownMenuItem(value: 'attendant', child: Text(s.adminStaffRoleAttendant)),
              ],
              onChanged: (val) => setState(() => _role = val ?? 'driver'),
            ),
            const SizedBox(height: 12),

            if (_role == 'driver') ...[
              TextField(
                controller: _licenseController,
                decoration: const InputDecoration(
                  labelText: 'Lambarka laysinka darawalnimada',
                  prefixIcon: Icon(Icons.credit_card_rounded),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
            ],

            const SizedBox(height: 10),
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

class _AssignCrewSheet extends ConsumerStatefulWidget {
  const _AssignCrewSheet();

  @override
  ConsumerState<_AssignCrewSheet> createState() => _AssignCrewSheetState();
}

class _AssignCrewSheetState extends ConsumerState<_AssignCrewSheet> {
  String? _selectedVehicleId;
  String? _selectedDriverId;
  String? _selectedAttendantId;
  bool _submitting = false;

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_selectedVehicleId == null || _selectedVehicleId!.isEmpty) {
      showNotice(context, s.adminSelectVehicle, isError: true);
      return;
    }
    if (_selectedDriverId == null || _selectedDriverId!.isEmpty) {
      showNotice(context, s.adminSelectDriver, isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).assignBusCrew(
        vehicleId: _selectedVehicleId!,
        driverId: _selectedDriverId!,
        attendantId: _selectedAttendantId,
      );
      if (mounted) {
        showNotice(context, s.adminBusCrewAssigned);
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
    final vehiclesAsync = ref.watch(adminVehiclesListProvider);
    final staffAsync = ref.watch(adminStaffMembersProvider);

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
                  s.adminAssignCrewToBus,
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

            // Select Vehicle
            vehiclesAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, __) => Text(s.adminSelectVehicle),
              data: (vehicles) => DropdownButtonFormField<String>(
                value: _selectedVehicleId,
                decoration: InputDecoration(
                  labelText: s.adminSelectVehicle,
                  prefixIcon: const Icon(Icons.directions_bus_rounded),
                  border: const OutlineInputBorder(),
                ),
                items: [
                  for (final v in vehicles)
                    DropdownMenuItem(value: v.id, child: Text(v.displayName)),
                ],
                onChanged: (val) => setState(() => _selectedVehicleId = val),
              ),
            ),
            const SizedBox(height: 12),

            // Select Driver
            staffAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, __) => Text(s.adminSelectDriver),
              data: (staffList) {
                final drivers = staffList.where((st) => st.role.toLowerCase() == 'driver').toList();
                return DropdownButtonFormField<String>(
                  value: _selectedDriverId,
                  decoration: InputDecoration(
                    labelText: s.adminSelectDriver,
                    prefixIcon: const Icon(Icons.airline_seat_recline_normal_rounded),
                    border: const OutlineInputBorder(),
                  ),
                  items: [
                    for (final d in drivers)
                      DropdownMenuItem(value: d.id, child: Text(d.fullName)),
                  ],
                  onChanged: (val) => setState(() => _selectedDriverId = val),
                );
              },
            ),
            const SizedBox(height: 12),

            // Select Attendant (optional)
            staffAsync.when(
              loading: () => const SizedBox.shrink(),
              error: (_, __) => const SizedBox.shrink(),
              data: (staffList) {
                final attendants = staffList.where((st) => st.role.toLowerCase() != 'driver').toList();
                return DropdownButtonFormField<String>(
                  value: _selectedAttendantId,
                  decoration: InputDecoration(
                    labelText: s.adminSelectAttendant,
                    prefixIcon: const Icon(Icons.supervised_user_circle_rounded),
                    border: const OutlineInputBorder(),
                  ),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Ma jiro (None)')),
                    for (final a in attendants)
                      DropdownMenuItem(value: a.id, child: Text(a.fullName)),
                  ],
                  onChanged: (val) => setState(() => _selectedAttendantId = val),
                );
              },
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
