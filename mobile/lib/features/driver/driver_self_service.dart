import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import 'driver_screens.dart' show CrewList;

/// Who works on the driver's buses today.
class CrewScreen extends ConsumerWidget {
  const CrewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    void refresh() => ref.invalidate(myCrewProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.crew)),
      body: AsyncBody<List<BusCrew>>(
        value: ref.watch(myCrewProvider),
        onRetry: refresh,
        builder: (crews) {
          if (crews.isEmpty) {
            return EmptyView(icon: Icons.groups_rounded, message: s.noCrew);
          }
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              for (final crew in crews) ...[
                SectionTitle(crew.vehicle.displayName),
                CrewList(members: crew.members),
              ],
            ],
          );
        },
      ),
    );
  }
}

/// The driver's own documents and whether anything the school requires is missing.
class DocumentsScreen extends ConsumerWidget {
  const DocumentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    void refresh() => ref.invalidate(myDocumentsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.documents)),
      body: AsyncBody<MyDocuments>(
        value: ref.watch(myDocumentsProvider),
        onRetry: refresh,
        builder: (mine) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (mine.isCompliant != null)
              SectionCard(
                child: Row(
                  children: [
                    Icon(
                      mine.isCompliant!
                          ? Icons.verified_rounded
                          : Icons.warning_amber_rounded,
                      color:
                          mine.isCompliant! ? RaadColors.green : RaadColors.red,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        mine.isCompliant!
                            ? s.compliant
                            : '${s.notCompliant}: ${mine.gaps.join(', ')}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            if (mine.documents.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 48),
                child: EmptyView(
                    icon: Icons.description_outlined, message: s.noDocuments),
              ),
            for (final d in mine.documents)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: SectionCard(
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(d.typeName,
                                style: const TextStyle(
                                    fontSize: 15.5,
                                    fontWeight: FontWeight.w700)),
                            if (d.number != null) Text(d.number!),
                            if (d.expiresOn != null)
                              Text(
                                s.expiresOn(friendlyDay(d.expiresOn!, s)),
                                style: TextStyle(color: context.muted),
                              ),
                          ],
                        ),
                      ),
                      if (d.daysLeft != null)
                        StatusChip(
                          label: s.daysLeft(d.daysLeft!),
                          color: d.daysLeft! < 0
                              ? RaadColors.red
                              : (d.status == 'valid'
                                  ? RaadColors.green
                                  : RaadColors.amber),
                        ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The days the driver has said they cannot work, and a form to report more.
class UnavailabilityScreen extends ConsumerWidget {
  const UnavailabilityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    void refresh() => ref.invalidate(myUnavailabilityProvider);

    Future<void> withdraw(Unavailability item) async {
      if (!await confirm(context, title: '${s.withdraw}?', s: s)) return;
      try {
        await ref.read(repositoryProvider).withdrawUnavailability(item.id);
      } catch (error) {
        if (context.mounted) showError(context, error, s);
      }
      refresh();
    }

    return Scaffold(
      appBar: AppBar(title: Text(s.unavailability)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final sent = await showModalBottomSheet<bool>(
            context: context,
            isScrollControlled: true,
            builder: (_) => const _UnavailabilityForm(),
          );
          if (sent == true) refresh();
        },
        icon: const Icon(Icons.add_rounded),
        label: Text(s.reportUnavailability),
      ),
      body: AsyncBody<List<Unavailability>>(
        value: ref.watch(myUnavailabilityProvider),
        onRetry: refresh,
        builder: (items) {
          if (items.isEmpty) {
            return EmptyView(
                icon: Icons.event_busy_rounded, message: s.noUnavailability);
          }
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
            itemCount: items.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final item = items[index];
              final days = item.startsOn == item.endsOn
                  ? friendlyDay(item.startsOn, s)
                  : '${friendlyDay(item.startsOn, s)} – ${friendlyDay(item.endsOn, s)}';
              return SectionCard(
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(days,
                              style: const TextStyle(
                                  fontSize: 15.5, fontWeight: FontWeight.w700)),
                          Text(s.unavailabilityReason(item.reason)),
                          if (item.note != null)
                            Text(item.note!,
                                style: TextStyle(color: context.muted)),
                        ],
                      ),
                    ),
                    if (item.isWithdrawn)
                      StatusChip(label: s.withdrawn, color: RaadColors.grey)
                    else if (item.isCovered)
                      StatusChip(label: s.covered, color: RaadColors.green)
                    else
                      TextButton(
                          onPressed: () => withdraw(item),
                          child: Text(s.withdraw)),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _UnavailabilityForm extends ConsumerStatefulWidget {
  const _UnavailabilityForm();

  @override
  ConsumerState<_UnavailabilityForm> createState() =>
      _UnavailabilityFormState();
}

class _UnavailabilityFormState extends ConsumerState<_UnavailabilityForm> {
  late DateTime _start = dateOnly(DateTime.now());
  late DateTime _end = _start;
  String _reason = 'sick';
  final _note = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _pick({required bool first}) async {
    final today = dateOnly(DateTime.now());
    final picked = await showDatePicker(
      context: context,
      initialDate: first ? _start : _end,
      firstDate: first ? today : _start,
      lastDate: today.add(const Duration(days: 180)),
    );
    if (picked == null) return;
    setState(() {
      if (first) {
        _start = picked;
        if (_end.isBefore(_start)) _end = _start;
      } else {
        _end = picked;
      }
    });
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(repositoryProvider).reportUnavailability(
            startsOn: _start,
            endsOn: _end,
            reason: _reason,
            note: _note.text,
          );
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) setState(() => _error = errorMessage(error, s));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    return Padding(
      padding: EdgeInsets.fromLTRB(
          20, 20, 20, 20 + MediaQuery.of(context).viewInsets.bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.reportUnavailability,
              style:
                  const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(s.unavailabilityNote, style: TextStyle(color: context.muted)),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _pick(first: true),
                  child: Text('${s.firstDay}\n${friendlyDay(_start, s)}',
                      textAlign: TextAlign.center),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _pick(first: false),
                  child: Text('${s.lastDay}\n${friendlyDay(_end, s)}',
                      textAlign: TextAlign.center),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue: _reason,
            decoration: InputDecoration(labelText: s.reason),
            items: [
              for (final r in const ['sick', 'personal', 'training', 'other'])
                DropdownMenuItem(
                    value: r, child: Text(s.unavailabilityReason(r))),
            ],
            onChanged: (value) => setState(() => _reason = value ?? 'sick'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _note,
            maxLength: 500,
            decoration: InputDecoration(labelText: s.note),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? s.loading : s.send),
          ),
        ],
      ),
    );
  }
}

/// The incidents the driver reported and how far the office has got with each.
class IncidentsScreen extends ConsumerWidget {
  const IncidentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    void refresh() => ref.invalidate(myIncidentsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(s.incidents)),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: RaadColors.red,
        foregroundColor: Colors.white,
        onPressed: () async {
          final sent = await Navigator.of(context).push<bool>(
            MaterialPageRoute(builder: (_) => const ReportIncidentScreen()),
          );
          if (sent == true) refresh();
        },
        icon: const Icon(Icons.report_rounded),
        label: Text(s.reportIncident),
      ),
      body: AsyncBody<List<IncidentReport>>(
        value: ref.watch(myIncidentsProvider),
        onRetry: refresh,
        builder: (items) {
          if (items.isEmpty) {
            return EmptyView(
                icon: Icons.report_gmailerrorred_rounded,
                message: s.noIncidents);
          }
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
            itemCount: items.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final i = items[index];
              final done = i.status == 'resolved' || i.status == 'closed';
              return SectionCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(i.title,
                              style: const TextStyle(
                                  fontSize: 15.5, fontWeight: FontWeight.w700)),
                        ),
                        StatusChip(
                          label: s.incidentStatus(i.status),
                          color: done ? RaadColors.green : RaadColors.blue,
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${s.incidentCategoryName(i.category)} · ${s.severityName(i.severity)} · '
                      '${friendlyMoment(i.occurredAt, s)}',
                      style: TextStyle(color: context.muted),
                    ),
                    if (i.description != null) ...[
                      const SizedBox(height: 6),
                      Text(i.description!),
                    ],
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class ReportIncidentScreen extends ConsumerStatefulWidget {
  const ReportIncidentScreen({super.key});

  @override
  ConsumerState<ReportIncidentScreen> createState() =>
      _ReportIncidentScreenState();
}

class _ReportIncidentScreenState extends ConsumerState<ReportIncidentScreen> {
  static const _categories = [
    'delay',
    'breakdown',
    'accident',
    'medical',
    'behaviour',
    'near_miss',
    'student_left_behind',
    'other',
  ];
  final _title = TextEditingController();
  final _description = TextEditingController();
  String _category = 'delay';
  String _severity = 'medium';
  String? _tripId;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_title.text.trim().length < 3) {
      setState(() => _error = s.titleTooShort);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(repositoryProvider).reportIncident(
            category: _category,
            severity: _severity,
            title: _title.text,
            description: _description.text,
            tripId: _tripId,
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(s.sent)));
      Navigator.pop(context, true);
    } catch (error) {
      if (mounted) setState(() => _error = errorMessage(error, s));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final today = dateOnly(DateTime.now());
    final trips = (ref.watch(driverTripsProvider).valueOrNull ?? const <Trip>[])
        .where((t) => t.scheduledDate == today)
        .toList();
    return Scaffold(
      appBar: AppBar(title: Text(s.reportIncident)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          DropdownButtonFormField<String>(
            initialValue: _category,
            decoration: InputDecoration(labelText: s.incidentCategory),
            items: [
              for (final c in _categories)
                DropdownMenuItem(
                    value: c, child: Text(s.incidentCategoryName(c))),
            ],
            onChanged: (value) => setState(() => _category = value ?? 'other'),
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue: _severity,
            decoration: InputDecoration(labelText: s.incidentSeverity),
            items: [
              for (final v in const ['low', 'medium', 'high', 'critical'])
                DropdownMenuItem(value: v, child: Text(s.severityName(v))),
            ],
            onChanged: (value) => setState(() => _severity = value ?? 'medium'),
          ),
          if (trips.isNotEmpty) ...[
            const SizedBox(height: 16),
            DropdownButtonFormField<String?>(
              initialValue: _tripId,
              decoration: InputDecoration(labelText: s.incidentTrip),
              items: [
                const DropdownMenuItem<String?>(value: null, child: Text('—')),
                for (final t in trips)
                  DropdownMenuItem<String?>(
                    value: t.id,
                    child: Text(
                      [
                        s.tripType(t.tripType),
                        if (t.routeName != null) t.routeName!,
                      ].join(' · '),
                    ),
                  ),
              ],
              onChanged: (value) => setState(() => _tripId = value),
            ),
          ],
          const SizedBox(height: 16),
          TextField(
            controller: _title,
            maxLength: 200,
            decoration: InputDecoration(labelText: s.incidentTitle),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _description,
            maxLines: 5,
            maxLength: 4000,
            decoration: InputDecoration(
                labelText: s.incidentDescription, alignLabelWithHint: true),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? s.loading : s.send),
          ),
        ],
      ),
    );
  }
}
