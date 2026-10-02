import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/config/env.dart';
import '../../core/l10n/strings.dart';
import '../../shared/widgets.dart';

/// One sign-in screen for both roles. The server decides the role; the app routes on it.
class LoginScreen extends ConsumerStatefulWidget {
  final bool sessionExpired;
  const LoginScreen({super.key, this.sessionExpired = false});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _identifierController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isSubmitting = false;
  bool _showPassword = false;
  String? _errorMessage;

  @override
  void dispose() {
    _identifierController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = ref.read(stringsProvider);
    final configurationError = Env.releaseConfigurationError;
    if (configurationError != null) {
      setState(() => _errorMessage = configurationError);
      return;
    }
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).login(
            identifier: _identifierController.text.trim(),
            password: _passwordController.text,
          );
    } catch (error) {
      if (mounted) setState(() => _errorMessage = errorMessage(error, s));
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(stringsProvider);
    final language = ref.watch(languageProvider);
    final message =
        _errorMessage ?? (widget.sessionExpired ? s.sessionExpired : null);
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.directions_bus_rounded,
                    size: 64, color: RaadColors.blue),
                const SizedBox(height: 8),
                const Text(
                  'RAAD',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 2),
                ),
                const SizedBox(height: 4),
                Text(
                  s.signInSubtitle,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: RaadColors.grey),
                ),
                const SizedBox(height: 32),
                TextField(
                  controller: _identifierController,
                  decoration: InputDecoration(
                    labelText: s.identifierLabel,
                    prefixIcon: const Icon(Icons.person_outline_rounded),
                  ),
                  keyboardType: TextInputType.emailAddress,
                  textInputAction: TextInputAction.next,
                  autocorrect: false,
                  enabled: !_isSubmitting,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _passwordController,
                  decoration: InputDecoration(
                    labelText: s.passwordLabel,
                    prefixIcon: const Icon(Icons.lock_outline_rounded),
                    suffixIcon: IconButton(
                      icon: Icon(
                        _showPassword
                            ? Icons.visibility_off_rounded
                            : Icons.visibility_rounded,
                      ),
                      onPressed: () =>
                          setState(() => _showPassword = !_showPassword),
                    ),
                  ),
                  obscureText: !_showPassword,
                  enabled: !_isSubmitting,
                  onSubmitted: (_) => _submit(),
                ),
                if (message != null) ...[
                  const SizedBox(height: 16),
                  Text(message,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
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
                      : Text(s.signIn),
                ),
                const SizedBox(height: 24),
                Center(
                  child: SegmentedButton<String>(
                    segments: [
                      ButtonSegment(value: 'so', label: Text(s.somali)),
                      ButtonSegment(value: 'en', label: Text(s.english)),
                    ],
                    selected: {language},
                    showSelectedIcon: false,
                    onSelectionChanged: (value) =>
                        ref.read(languageProvider.notifier).state = value.first,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
