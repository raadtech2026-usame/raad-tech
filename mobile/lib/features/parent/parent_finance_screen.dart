import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/data/models.dart';
import '../../core/data/repository.dart';
import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';

/// The Parent Finance screen: shows monthly bus fees for all children,
/// invoice statuses (paid, unpaid, overdue), and payment receipts.
class ParentFinanceScreen extends ConsumerWidget {
  const ParentFinanceScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(stringsProvider);
    final finance = ref.watch(parentInvoicesProvider);

    void refresh() {
      ref.invalidate(parentInvoicesProvider);
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(s.financeTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Cusbooneysii',
            onPressed: refresh,
          ),
        ],
      ),
      body: AsyncBody<ParentFinanceSummary>(
        value: finance,
        onRetry: refresh,
        builder: (summary) {
          final invoices = summary.invoices;
          final payments = summary.payments;

          return RefreshIndicator(
            onRefresh: () async => refresh(),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              children: [
                _SummaryOverviewCard(summary: summary),
                const SizedBox(height: 16),

                // Per-child breakdown across latest active invoice
                if (invoices.isNotEmpty && invoices.first.lines.isNotEmpty) ...[
                  const SectionTitle('Carruurta & Lacagaha Baska'),
                  _ChildrenFeeCard(
                    lines: invoices.first.lines,
                    currency: summary.currency,
                  ),
                  const SizedBox(height: 16),
                ],

                // Invoices Section
                const SectionTitle('Biilasha Dugsiga (Invoices)'),
                if (invoices.isEmpty)
                  SectionCard(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 20),
                      child: Center(
                        child: Column(
                          children: [
                            Icon(Icons.receipt_long_rounded,
                                size: 40, color: context.muted),
                            const SizedBox(height: 8),
                            Text(
                              s.noInvoices,
                              style: TextStyle(color: context.muted),
                            ),
                          ],
                        ),
                      ),
                    ),
                  )
                else
                  for (final inv in invoices) ...[
                    _InvoiceCard(invoice: inv),
                    const SizedBox(height: 10),
                  ],

                const SizedBox(height: 16),

                // Payment Receipts Section
                SectionTitle(s.paymentReceipts),
                if (payments.isEmpty)
                  SectionCard(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 20),
                      child: Center(
                        child: Column(
                          children: [
                            Icon(Icons.payment_rounded,
                                size: 40, color: context.muted),
                            const SizedBox(height: 8),
                            Text(
                              s.noPaymentsRecorded,
                              style: TextStyle(color: context.muted),
                            ),
                          ],
                        ),
                      ),
                    ),
                  )
                else
                  for (final payment in payments) ...[
                    _PaymentReceiptCard(payment: payment),
                    const SizedBox(height: 8),
                  ],

                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest
                        .withValues(alpha: 0.5),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: Theme.of(context).colorScheme.outlineVariant,
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.info_outline_rounded,
                          size: 18, color: context.muted),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'Marka aad bixiso lacagta baska, maamulka dugsiga (Org Admin) ayaa xaqiijinaya oo calaamadinaya in la bixiyay.',
                          style: TextStyle(fontSize: 12, color: context.muted),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SummaryOverviewCard extends StatelessWidget {
  final ParentFinanceSummary summary;
  const _SummaryOverviewCard({required this.summary});

  @override
  Widget build(BuildContext context) {
    final s = Strings(Localizations.localeOf(context).languageCode == 'so');
    final hasBalance = summary.hasOutstanding;
    final balanceVal = double.tryParse(summary.balanceDue) ?? 0.0;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            Theme.of(context).colorScheme.primaryContainer,
            Theme.of(context).colorScheme.surface,
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: Theme.of(context).colorScheme.outlineVariant,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Xaaladda Lacagaha',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: context.muted,
                ),
              ),
              StatusChip(
                label: hasBalance
                    ? 'Dhiman: \$${summary.balanceDue}'
                    : 'Bixiyay (Settled)',
                color: hasBalance ? RaadColors.amber : RaadColors.green,
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _FinanceKpi(
                  label: s.totalDueLabel,
                  amount: '\$${summary.totalDue}',
                  color: Theme.of(context).colorScheme.onSurface,
                ),
              ),
              Container(height: 36, width: 1, color: context.muted.withValues(alpha: 0.2)),
              Expanded(
                child: _FinanceKpi(
                  label: s.totalPaidLabel,
                  amount: '\$${summary.totalPaid}',
                  color: RaadColors.green,
                ),
              ),
              Container(height: 36, width: 1, color: context.muted.withValues(alpha: 0.2)),
              Expanded(
                child: _FinanceKpi(
                  label: s.balanceDueLabel,
                  amount: '\$${summary.balanceDue}',
                  color: balanceVal > 0 ? RaadColors.red : RaadColors.green,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _FinanceKpi extends StatelessWidget {
  final String label;
  final String amount;
  final Color color;

  const _FinanceKpi({
    required this.label,
    required this.amount,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          amount,
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w800,
            color: color,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(fontSize: 11.5, color: context.muted),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

class _ChildrenFeeCard extends StatelessWidget {
  final List<ParentInvoiceLine> lines;
  final String currency;

  const _ChildrenFeeCard({required this.lines, required this.currency});

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (int i = 0; i < lines.length; i++) ...[
            if (i > 0) const Divider(height: 16),
            Row(
              children: [
                CircleAvatar(
                  radius: 16,
                  backgroundColor: lines[i].isPaid
                      ? RaadColors.green.withValues(alpha: 0.15)
                      : RaadColors.amber.withValues(alpha: 0.15),
                  child: Icon(
                    lines[i].isPaid ? Icons.check_circle_rounded : Icons.person_rounded,
                    size: 18,
                    color: lines[i].isPaid ? RaadColors.green : RaadColors.amber,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        lines[i].fullName,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 14.5,
                        ),
                      ),
                      Text(
                        lines[i].isPaid
                            ? 'Waa la bixiyay'
                            : 'Dhiman: \$${lines[i].balanceDue}',
                        style: TextStyle(
                          fontSize: 12,
                          color: lines[i].isPaid ? RaadColors.green : RaadColors.red,
                        ),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '\$${lines[i].amount}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 15,
                      ),
                    ),
                    Text(
                      'Bisha',
                      style: TextStyle(fontSize: 11, color: context.muted),
                    ),
                  ],
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _InvoiceCard extends StatelessWidget {
  final ParentInvoice invoice;
  const _InvoiceCard({required this.invoice});

  Color _statusColor(String status) {
    switch (status) {
      case 'paid':
        return RaadColors.green;
      case 'partially_paid':
        return RaadColors.amber;
      case 'overdue':
        return RaadColors.red;
      default:
        return RaadColors.grey;
    }
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'paid':
        return 'Waa la bixiyay';
      case 'partially_paid':
        return 'Qayb baa la bixiyay';
      case 'overdue':
        return 'Wuu dhaaftay';
      default:
        return 'Wali lama bixin';
    }
  }

  @override
  Widget build(BuildContext context) {
    final statusColor = _statusColor(invoice.status);
    final statusText = _statusLabel(invoice.status);

    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.receipt_rounded, color: statusColor, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Biilka: ${invoice.period}',
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                ),
              ),
              StatusChip(label: statusText, color: statusColor),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Lambarka: #${invoice.invoiceNumber}',
                style: TextStyle(fontSize: 12, color: context.muted),
              ),
              if (invoice.dueDate.isNotEmpty)
                Text(
                  'Bixi ka hor: ${invoice.dueDate}',
                  style: TextStyle(fontSize: 12, color: context.muted),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Wadarta: \$${invoice.amount}',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                Text('Bixiyay: \$${invoice.amountPaid}',
                    style: const TextStyle(fontSize: 13, color: RaadColors.green, fontWeight: FontWeight.w600)),
                Text('Dhiman: \$${invoice.balanceDue}',
                    style: TextStyle(
                      fontSize: 13,
                      color: (double.tryParse(invoice.balanceDue) ?? 0) > 0 ? RaadColors.red : RaadColors.green,
                      fontWeight: FontWeight.bold,
                    )),
              ],
            ),
          ),
          if (invoice.lines.isNotEmpty) ...[
            const SizedBox(height: 8),
            for (final line in invoice.lines)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    const Icon(Icons.circle, size: 6, color: RaadColors.grey),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        line.fullName,
                        style: const TextStyle(fontSize: 12.5),
                      ),
                    ),
                    Text(
                      '\$${line.amount}',
                      style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _PaymentReceiptCard extends StatelessWidget {
  final ParentPaymentReceipt payment;
  const _PaymentReceiptCard({required this.payment});

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      child: Row(
        children: [
          CircleAvatar(
            radius: 16,
            backgroundColor: RaadColors.green.withValues(alpha: 0.15),
            child: const Icon(Icons.check_rounded, color: RaadColors.green, size: 18),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Rasiidh #${payment.receiptNumber}',
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13.5),
                ),
                Text(
                  'Taariikh: ${payment.paymentDate} · Habka: ${payment.paymentMethod}',
                  style: TextStyle(fontSize: 11.5, color: context.muted),
                ),
              ],
            ),
          ),
          Text(
            '+\$${payment.amount}',
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w800,
              color: RaadColors.green,
            ),
          ),
        ],
      ),
    );
  }
}
