import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Light, dark, or follow the phone. Follows the phone until the person chooses, the same rule
/// the web dashboard uses (`frontend/src/shared/theme/themeStore.ts`). The choice is kept on
/// the device; if it cannot be read or written the app simply follows the phone.
class ThemeModeController extends StateNotifier<ThemeMode> {
  static const _key = 'raad_theme_mode';
  final FlutterSecureStorage _storage;

  ThemeModeController({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage(),
        super(ThemeMode.system) {
    _load();
  }

  Future<void> _load() async {
    try {
      final saved = await _storage.read(key: _key);
      final mode = ThemeMode.values.where((m) => m.name == saved).firstOrNull;
      if (mode != null && mounted) state = mode;
    } catch (_) {
      // No stored choice available: keep following the phone.
    }
  }

  Future<void> set(ThemeMode mode) async {
    state = mode;
    try {
      await _storage.write(key: _key, value: mode.name);
    } catch (_) {
      // The choice still applies for this run.
    }
  }
}

final themeModeProvider = StateNotifierProvider<ThemeModeController, ThemeMode>(
    (ref) => ThemeModeController());
