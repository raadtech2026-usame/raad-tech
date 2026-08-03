import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import 'live_tracking_screen.dart';

/// Phase M3 (docs/architecture/frontend-flutter-master-roadmap.md §5): "Assigned children
/// list, live GPS map during active trips only, trip history, transport-payment status,
/// notification center." **A real, previously-undiscovered backend gap blocks the first item
/// on that list**, found while building this exact screen (Priority 1 Item 9,
/// `PROJECT_STATUS.md`):
///
/// There is currently no safe backend endpoint for a Parent to list their own children.
/// `GET /parents/{parent_id}/students` (`transport_ops/api/routers.py`) requires
/// `transport_ops.student_parents.list`, a permission the seeded RBAC matrix grants to Org
/// Admin only — the `parent` role does not hold it, so a real Parent principal gets 403 calling
/// it today. Even if that permission were granted, the route has **no ownership check at all**:
/// `parent_id` is taken directly from the path with nothing verifying it matches the caller's
/// own linked `Parent` record — granting the permission without also adding that check would
/// let any parent pass any other parent's `parent_id` and see their children, a real
/// cross-parent privacy leak in the same family of issue ADR-0021's tenant-isolation audit
/// already fixed for organization-level scoping. Closing this safely needs a genuine backend
/// change (most likely a new, inherently self-scoped `GET /me/students`, resolving the caller's
/// own `Parent` record from `Principal.user_id` server-side rather than trusting a client-
/// supplied id) — a real design/security decision, not something to invent under time pressure
/// inside this mobile-app task. See `PROJECT_STATUS.md`'s own new Known Issue for the full
/// writeup and recommended fix.
///
/// This screen is honest about that rather than fabricating a working list: it explains the
/// gap, and offers the one thing that **is** safely reachable today — tracking a specific
/// vehicle by id, for demonstrating/testing `LiveTrackingScreen`'s real, complete WebSocket
/// implementation once a real vehicle/trip exists to point it at. This is a stand-in entry
/// point, not the intended production UX (a parent should never need to know a vehicle's
/// internal id) — labeled as such below, not silently presented as finished.
class ParentHomeScreen extends ConsumerStatefulWidget {
  const ParentHomeScreen({super.key});

  @override
  ConsumerState<ParentHomeScreen> createState() => _ParentHomeScreenState();
}

class _ParentHomeScreenState extends ConsumerState<ParentHomeScreen> {
  final _vehicleIdController = TextEditingController();

  @override
  void dispose() {
    _vehicleIdController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Children'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              child: const Padding(
                padding: EdgeInsets.all(16),
                child: Text(
                  'Your children\'s list isn\'t available yet — this needs a backend change '
                  '(a self-scoped "my students" endpoint) that hasn\'t been built. See '
                  'PROJECT_STATUS.md for the full explanation.',
                ),
              ),
            ),
            const SizedBox(height: 24),
            Text(
              'For testing: track a vehicle directly by id',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _vehicleIdController,
              decoration: const InputDecoration(
                labelText: 'Vehicle ID',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () {
                final vehicleId = _vehicleIdController.text.trim();
                if (vehicleId.isEmpty) return;
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => LiveTrackingScreen(vehicleId: vehicleId),
                  ),
                );
              },
              child: const Text('Track'),
            ),
          ],
        ),
      ),
    );
  }
}
