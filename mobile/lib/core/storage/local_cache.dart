import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Lightweight offline cache backed by FlutterSecureStorage and an in-memory map.
/// Caches GET responses (rosters, trips, profile, admin board) to prevent blank
/// screens when the network drops.
class LocalCache {
  static const _prefix = 'raad_cache_';

  final FlutterSecureStorage _storage;
  final Map<String, dynamic> _memory = {};

  LocalCache({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  String _key(String path) => '$_prefix$path';

  Future<void> putJson(String path, dynamic data) async {
    _memory[path] = data;
    try {
      await _storage.write(key: _key(path), value: jsonEncode(data));
    } catch (_) {
      // Storage errors should never crash network flows
    }
  }

  Future<dynamic> getJson(String path) async {
    if (_memory.containsKey(path)) {
      return _memory[path];
    }
    try {
      final raw = await _storage.read(key: _key(path));
      if (raw == null) return null;
      final parsed = jsonDecode(raw);
      _memory[path] = parsed;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  Future<Map<String, dynamic>?> getMap(String path) async {
    final data = await getJson(path);
    return data is Map<String, dynamic> ? data : null;
  }

  Future<List<Map<String, dynamic>>?> getList(String path) async {
    final data = await getJson(path);
    if (data is! List) return null;
    return data.whereType<Map<String, dynamic>>().toList();
  }

  Future<void> remove(String path) async {
    _memory.remove(path);
    try {
      await _storage.delete(key: _key(path));
    } catch (_) {}
  }

  Future<void> clear() async {
    _memory.clear();
    try {
      final all = await _storage.readAll();
      for (final k in all.keys) {
        if (k.startsWith(_prefix)) {
          await _storage.delete(key: k);
        }
      }
    } catch (_) {}
  }
}
