import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';

/// Shown when [voluntary] is false (default): the app blocks until the forced temp-password is
/// replaced. When [voluntary] is true (launched from Profile): a back-arrow is shown so the
/// user can dismiss the screen without being signed out.
class ChangePasswordScreen extends ConsumerStatefulWidget {
  final bool voluntary;
  const ChangePasswordScreen({super.key, this.voluntary = false});

  @override
  ConsumerState<ChangePasswordScreen> createState() =>
      _ChangePasswordScreenState();
}

/// Convenience: open the voluntary change-password sheet from anywhere.
Future<void> openChangePasswordScreen(BuildContext context) {
  return Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => const ChangePasswordScreen(voluntary: true),
    ),
  );
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _first = TextEditingController();
  final _second = TextEditingController();
  bool _isSubmitting = false;
  String? _errorMessage;

  @override
  void dispose() {
    _first.dispose();
    _second.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    if (_first.text.length < 8) {
      setState(() => _errorMessage = s.passwordTooShort);
      return;
    }
    if (_first.text != _second.text) {
      setState(() => _errorMessage = s.passwordsDiffer);
      return;
    }
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .changePassword(_first.text);
      if (mounted && widget.voluntary) {
        showNotice(context, s.passwordChanged);
        Navigator.of(context).pop();
      }
    } catch (error) {
      if (mounted) setState(() => _errorMessage = errorMessage(error, s));
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(s.changePasswordTitle),
        // In voluntary mode a back arrow is shown automatically; in forced mode
        // the only exit is sign-out (the app has nowhere else to go until the
        // temp password is replaced).
        automaticallyImplyLeading: widget.voluntary,
        actions: [
          if (!widget.voluntary)
            TextButton(
              onPressed: () => ref.read(authControllerProvider.notifier).logout(),
              child: Text(s.signOut),
            ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text(
              widget.voluntary
                  ? s.changePasswordVoluntaryIntro
                  : s.changePasswordIntro,
              style: const TextStyle(fontSize: 15.5),
            ),
            const SizedBox(height: 24),
            TextField(
              controller: _first,
              obscureText: true,
              enabled: !_isSubmitting,
              decoration: InputDecoration(labelText: s.newPassword),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _second,
              obscureText: true,
              enabled: !_isSubmitting,
              decoration: InputDecoration(labelText: s.repeatPassword),
              onSubmitted: (_) => _submit(),
            ),
            if (_errorMessage != null) ...[
              const SizedBox(height: 16),
              Text(
                _errorMessage!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _isSubmitting ? null : _submit,
              child: _isSubmitting
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
