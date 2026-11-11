import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/strings.dart';
import '../../core/util/format.dart';
import '../../shared/widgets.dart';
import 'admin_data.dart';
import 'admin_screens.dart';

/// Pillar 1: School ERP Finance.
/// Allows the Org Admin to inspect financial health (Billed, Collected, Outstanding),
/// track student fee invoices, issue new invoices, and record mobile/cash payments.
class AdminFinanceScreen extends ConsumerStatefulWidget {
  const AdminFinanceScreen({super.key});

  @override
  ConsumerState<AdminFinanceScreen> createState() => _AdminFinanceScreenState();
}

class _AdminFinanceScreenState extends ConsumerState<AdminFinanceScreen> {
  String _statusFilter = 'all'; // all, paid, pending, overdue

  Future<void> _refresh() async {
    ref.invalidate(adminFinanceSummaryProvider);
    ref.invalidate(adminInvoicesListProvider);
    await ref.read(adminFinanceSummaryProvider.future);
  }

  void _showIssueInvoiceSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => const _IssueInvoiceSheet(),
    ).then((_) => _refresh());
  }

  void _showRecordPaymentSheet([AdminInvoice? preselectedInvoice]) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => _RecordPaymentSheet(initialInvoice: preselectedInvoice),
    ).then((_) => _refresh());
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final summaryAsync = ref.watch(adminFinanceSummaryProvider);
    final invoicesAsync = ref.watch(adminInvoicesListProvider);

    return Scaffold(
      appBar: AppBar(
        title: Text(s.adminFinanceOverviewTitle),
        actions: adminTopActions(context, ref, onRefresh: _refresh),
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_card_rounded),
        label: Text(s.adminRecordPayment),
        onPressed: () => _showRecordPaymentSheet(),
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
          children: [
            // KPI Overview Cards
            summaryAsync.when(
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (err, _) => SectionCard(
                child: Row(
                  children: [
                    const Icon(Icons.error_outline_rounded, color: RaadColors.red),
                    const SizedBox(width: 12),
                    Expanded(child: Text(errorMessage(err, s))),
                    OutlinedButton(onPressed: _refresh, child: Text(s.retry)),
                  ],
                ),
              ),
              data: (summary) => _FinanceKpis(summary: summary),
            ),
            const SizedBox(height: 16),

            // Quick Actions: Issue invoice & Record payment
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.receipt_long_rounded, size: 18),
                    label: Text(s.adminIssueInvoice, maxLines: 1, overflow: TextOverflow.ellipsis),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                    onPressed: _showIssueInvoiceSheet,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.payments_outlined, size: 18),
                    label: Text(s.adminRecordPayment, maxLines: 1, overflow: TextOverflow.ellipsis),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                    onPressed: () => _showRecordPaymentSheet(),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),

            // Invoices Section Header & Filter Chips
            Row(
              children: [
                Expanded(
                  child: Text(
                    s.adminInvoiceList,
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  _filterChip(s.adminFilterAll, 'all'),
                  const SizedBox(width: 6),
                  _filterChip(s.adminInvoiceStatusPending, 'pending'),
                  const SizedBox(width: 6),
                  _filterChip(s.adminInvoiceStatusPaid, 'paid'),
                  const SizedBox(width: 6),
                  _filterChip(s.adminInvoiceStatusOverdue, 'overdue'),
                ],
              ),
            ),
            const SizedBox(height: 12),

            // Invoice Items
            invoicesAsync.when(
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 32),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (err, _) => SectionCard(
                child: Text(errorMessage(err, s)),
              ),
              data: (invoices) {
                final filtered = invoices.where((inv) {
                  if (_statusFilter == 'all') return true;
                  return inv.status.toLowerCase() == _statusFilter;
                }).toList();

                if (filtered.isEmpty) {
                  return SectionCard(
                    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.receipt_outlined, size: 40, color: context.muted),
                          const SizedBox(height: 12),
                          Text(
                            s.emptyState,
                            style: TextStyle(color: context.muted, fontSize: 14),
                          ),
                        ],
                      ),
                    ),
                  );
                }

                return Column(
                  children: [
                    for (final inv in filtered)
                      _InvoiceCard(
                        invoice: inv,
                        onRecordPayment: () => _showRecordPaymentSheet(inv),
                      ),
                  ],
                );
              },
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

class _FinanceKpis extends StatelessWidget {
  final AdminFinanceSummary summary;
  const _FinanceKpis({required this.summary});

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _KpiBox(
                title: s.adminTotalBilled,
                amount: '\$${summary.billedAmount}',
                icon: Icons.account_balance_wallet_outlined,
                color: Colors.blueAccent,
                countLabel: '${summary.invoiceCount} qaansheeg',
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _KpiBox(
                title: s.adminTotalCollected,
                amount: '\$${summary.collectedAmount}',
                icon: Icons.check_circle_outline_rounded,
                color: RaadColors.green,
                countLabel: '${summary.paidInvoiceCount} bixiyay',
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        _KpiBox(
          title: s.adminTotalOutstanding,
          amount: '\$${summary.outstandingAmount}',
          icon: Icons.pending_actions_rounded,
          color: RaadColors.amber,
          countLabel: '${summary.overdueInvoiceCount} dib u dhacay',
          isWide: true,
        ),
      ],
    );
  }
}

class _KpiBox extends StatelessWidget {
  final String title;
  final String amount;
  final IconData icon;
  final Color color;
  final String countLabel;
  final bool isWide;

  const _KpiBox({
    required this.title,
    required this.amount,
    required this.icon,
    required this.color,
    required this.countLabel,
    this.isWide = false,
  });

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: context.muted,
                ),
              ),
              Icon(icon, size: 20, color: color),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            amount,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.5,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            countLabel,
            style: TextStyle(fontSize: 11.5, color: context.muted),
          ),
        ],
      ),
    );
  }
}

class _InvoiceCard extends StatelessWidget {
  final AdminInvoice invoice;
  final VoidCallback onRecordPayment;

  const _InvoiceCard({
    required this.invoice,
    required this.onRecordPayment,
  });

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'paid':
        return RaadColors.green;
      case 'overdue':
        return RaadColors.red;
      case 'pending':
      default:
        return RaadColors.amber;
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    final color = _statusColor(invoice.status);
    final isSettled = invoice.isPaid || double.tryParse(invoice.balanceDue) == 0;

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
                Expanded(
                  child: Text(
                    invoice.studentName ?? 'Arday: ${invoice.studentId.substring(0, invoice.studentId.length > 8 ? 8 : invoice.studentId.length)}',
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    invoice.status.toUpperCase(),
                    style: TextStyle(
                      color: color,
                      fontWeight: FontWeight.bold,
                      fontSize: 11,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Icon(Icons.calendar_month_outlined, size: 14, color: context.muted),
                const SizedBox(width: 4),
                Text(
                  '${s.adminPeriod}: ${invoice.period}',
                  style: TextStyle(color: context.muted, fontSize: 12),
                ),
                if (invoice.dueDate != null) ...[
                  const SizedBox(width: 12),
                  Icon(Icons.schedule_rounded, size: 14, color: context.muted),
                  const SizedBox(width: 4),
                  Text(
                    'Due: ${invoice.dueDate}',
                    style: TextStyle(color: context.muted, fontSize: 12),
                  ),
                ],
              ],
            ),
            const Divider(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${s.adminAmountDollars}: \$${invoice.amount}',
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Dhiman: \$${invoice.balanceDue}',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: isSettled ? RaadColors.green : RaadColors.red,
                      ),
                    ),
                  ],
                ),
                if (!isSettled)
                  ElevatedButton.icon(
                    icon: const Icon(Icons.payment_rounded, size: 15),
                    label: Text(s.adminRecordPayment, style: const TextStyle(fontSize: 12)),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                      minimumSize: Size.zero,
                    ),
                    onPressed: onRecordPayment,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _IssueInvoiceSheet extends ConsumerStatefulWidget {
  const _IssueInvoiceSheet();

  @override
  ConsumerState<_IssueInvoiceSheet> createState() => _IssueInvoiceSheetState();
}

class _IssueInvoiceSheetState extends ConsumerState<_IssueInvoiceSheet> {
  final _amountController = TextEditingController();
  final _periodController = TextEditingController();
  final _notesController = TextEditingController();
  String? _selectedStudentId;
  DateTime? _dueDate;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _periodController.text = '${now.year}-${now.month.toString().padLeft(2, '0')}';
  }

  @override
  void dispose() {
    _amountController.dispose();
    _periodController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_selectedStudentId == null || _selectedStudentId!.isEmpty) {
      showNotice(context, s.adminSelectStudent, isError: true);
      return;
    }
    final amount = double.tryParse(_amountController.text.trim());
    if (amount == null || amount <= 0) {
      showNotice(context, 'Gali cadad sax ah', isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).issueInvoice(
        studentId: _selectedStudentId!,
        period: _periodController.text.trim(),
        amount: amount,
        dueDate: _dueDate != null ? isoDate(_dueDate!) : null,
        notes: _notesController.text.trim(),
      );
      if (mounted) {
        showNotice(context, 'Qaansheegta si guul leh ayaa loo soo saaray');
        Navigator.of(context).pop();
      }
    } catch (err) {
      if (mounted) {
        showNotice(context, errorMessage(err, s), isError: true);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final studentsAsync = ref.watch(adminStudentsProvider);

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
                  s.adminIssueInvoice,
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

            // Student picker
            studentsAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, __) => Text(s.adminSelectStudent),
              data: (students) => DropdownButtonFormField<String>(
                value: _selectedStudentId,
                decoration: InputDecoration(
                  labelText: s.adminSelectStudent,
                  prefixIcon: const Icon(Icons.person_rounded),
                  border: const OutlineInputBorder(),
                ),
                items: [
                  for (final st in students)
                    DropdownMenuItem(
                      value: st.id,
                      child: Text(st.fullName.isNotEmpty ? st.fullName : st.id),
                    ),
                ],
                onChanged: (val) => setState(() => _selectedStudentId = val),
              ),
            ),
            const SizedBox(height: 12),

            // Amount field
            TextField(
              controller: _amountController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: s.adminAmountDollars,
                prefixIcon: const Icon(Icons.attach_money_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Period
            TextField(
              controller: _periodController,
              decoration: InputDecoration(
                labelText: s.adminPeriod,
                prefixIcon: const Icon(Icons.calendar_month_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Due Date
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event_rounded),
              title: Text(
                _dueDate == null
                    ? s.adminDueDate
                    : '${s.adminDueDate}: ${isoDate(_dueDate!)}',
              ),
              trailing: OutlinedButton(
                onPressed: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now().add(const Duration(days: 15)),
                    firstDate: DateTime.now().subtract(const Duration(days: 30)),
                    lastDate: DateTime.now().add(const Duration(days: 180)),
                  );
                  if (picked != null) setState(() => _dueDate = picked);
                },
                child: const Text('Dooro'),
              ),
            ),
            const SizedBox(height: 8),

            // Notes
            TextField(
              controller: _notesController,
              decoration: InputDecoration(
                labelText: s.adminNotes,
                prefixIcon: const Icon(Icons.note_alt_outlined),
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

class _RecordPaymentSheet extends ConsumerStatefulWidget {
  final AdminInvoice? initialInvoice;
  const _RecordPaymentSheet({this.initialInvoice});

  @override
  ConsumerState<_RecordPaymentSheet> createState() => _RecordPaymentSheetState();
}

class _RecordPaymentSheetState extends ConsumerState<_RecordPaymentSheet> {
  final _amountController = TextEditingController();
  final _referenceController = TextEditingController();
  final _notesController = TextEditingController();
  String? _selectedInvoiceId;
  String _paymentMethod = 'EVC Plus';
  bool _submitting = false;

  final _methods = const ['EVC Plus', 'Zaad', 'Sahal', 'Kaash (Cash)', 'Bank'];

  @override
  void initState() {
    super.initState();
    if (widget.initialInvoice != null) {
      _selectedInvoiceId = widget.initialInvoice!.id;
      _amountController.text = widget.initialInvoice!.balanceDue;
    }
  }

  @override
  void dispose() {
    _amountController.dispose();
    _referenceController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_selectedInvoiceId == null || _selectedInvoiceId!.isEmpty) {
      showNotice(context, 'Dooro qaansheegta', isError: true);
      return;
    }
    final amount = double.tryParse(_amountController.text.trim());
    if (amount == null || amount <= 0) {
      showNotice(context, 'Gali cadad sax ah', isError: true);
      return;
    }

    setState(() => _submitting = true);
    try {
      await ref.read(adminRepositoryProvider).recordPayment(
        invoiceId: _selectedInvoiceId!,
        amount: amount,
        method: _paymentMethod,
        reference: _referenceController.text.trim(),
        notes: _notesController.text.trim(),
      );
      if (mounted) {
        showNotice(context, 'Lacag-bixinta si guul leh ayaa loo diiwaangeliyay');
        Navigator.of(context).pop();
      }
    } catch (err) {
      if (mounted) {
        showNotice(context, errorMessage(err, s), isError: true);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final invoicesAsync = ref.watch(adminInvoicesListProvider);

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
                  s.adminRecordPayment,
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

            // Invoice selection dropdown
            invoicesAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, __) => Text(s.adminInvoiceNumber),
              data: (invoices) => DropdownButtonFormField<String>(
                value: _selectedInvoiceId,
                decoration: InputDecoration(
                  labelText: s.adminInvoiceNumber,
                  prefixIcon: const Icon(Icons.receipt_rounded),
                  border: const OutlineInputBorder(),
                ),
                items: [
                  for (final inv in invoices)
                    DropdownMenuItem(
                      value: inv.id,
                      child: Text(
                        '${inv.studentName ?? 'Invoice'} - \$${inv.balanceDue} (${inv.period})',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (val) {
                  setState(() {
                    _selectedInvoiceId = val;
                    final selected = invoices.firstWhere((i) => i.id == val);
                    _amountController.text = selected.balanceDue;
                  });
                },
              ),
            ),
            const SizedBox(height: 12),

            // Amount field
            TextField(
              controller: _amountController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: s.adminAmountDollars,
                prefixIcon: const Icon(Icons.attach_money_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Payment method dropdown
            DropdownButtonFormField<String>(
              value: _paymentMethod,
              decoration: InputDecoration(
                labelText: s.adminPaymentMethod,
                prefixIcon: const Icon(Icons.account_balance_rounded),
                border: const OutlineInputBorder(),
              ),
              items: [
                for (final m in _methods)
                  DropdownMenuItem(value: m, child: Text(m)),
              ],
              onChanged: (val) => setState(() => _paymentMethod = val ?? 'EVC Plus'),
            ),
            const SizedBox(height: 12),

            // Reference (e.g. mobile transaction code)
            TextField(
              controller: _referenceController,
              decoration: InputDecoration(
                labelText: s.adminReference,
                prefixIcon: const Icon(Icons.tag_rounded),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),

            // Notes
            TextField(
              controller: _notesController,
              decoration: InputDecoration(
                labelText: s.adminNotes,
                prefixIcon: const Icon(Icons.note_alt_outlined),
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
