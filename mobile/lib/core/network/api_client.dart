import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/env.dart';
import '../storage/local_cache.dart';
import 'api_exception.dart';

/// REST client for the RAAD Business API.
///
/// Holds the access token in memory only (`.claude/rules/flutter.md` #5: the refresh token is
/// the one that lives in secure storage). When a call answers 401, [onUnauthorized] is asked
/// once to obtain a fresh access token and the call is repeated; if that fails the caller gets
/// the 401 and the app signs out.
///
/// Incorporates a [LocalCache] so network drops return the last-known cached JSON
/// payload for read requests rather than throwing blank screen errors.
class ApiClient {
  static const Duration timeout = Duration(seconds: 20);

  final http.Client _client;
  final LocalCache _cache;
  String? _accessToken;

  /// Set by the auth controller. Returns true when a new access token is in place.
  Future<bool> Function()? onUnauthorized;
  Future<bool>? _refreshing;

  ApiClient({http.Client? client, LocalCache? cache})
      : _client = client ?? http.Client(),
        _cache = cache ?? LocalCache();

  String? get accessToken => _accessToken;

  LocalCache get cache => _cache;

  void setAccessToken(String token) => _accessToken = token;

  void clearAccessToken() => _accessToken = null;

  Future<void> clearCache() => _cache.clear();

  Map<String, String> _headers(bool auth) {
    return {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      if (auth && _accessToken != null) 'Authorization': 'Bearer $_accessToken',
    };
  }

  Future<Map<String, dynamic>> get(String path,
      {bool auth = true, bool cache = true}) async {
    try {
      final decoded = await _send('GET', path, auth: auth);
      final result =
          decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
      if (cache && result.isNotEmpty) {
        await _cache.putJson(path, result);
      }
      return result;
    } on ApiException catch (e) {
      if (cache && e.isNetwork) {
        final cached = await _cache.getMap(path);
        if (cached != null) return cached;
      }
      rethrow;
    }
  }

  /// For endpoints that answer with a JSON array (`/me/students`, `/me/trips`, ...).
  Future<List<Map<String, dynamic>>> getList(String path,
      {bool cache = true}) async {
    try {
      final decoded = await _send('GET', path, auth: true);
      if (decoded is! List) return const [];
      final result = decoded.whereType<Map<String, dynamic>>().toList();
      if (cache && result.isNotEmpty) {
        await _cache.putJson(path, result);
      }
      return result;
    } on ApiException catch (e) {
      if (cache && e.isNetwork) {
        final cached = await _cache.getList(path);
        if (cached != null) return cached;
      }
      rethrow;
    }
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? body,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final decoded = await _send('POST', path,
        auth: auth, body: body, extraHeaders: extraHeaders);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  }

  Future<Map<String, dynamic>> patch(
    String path, {
    Map<String, dynamic>? body,
    Map<String, dynamic>? data,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final decoded = await _send('PATCH', path,
        auth: auth, body: body ?? data, extraHeaders: extraHeaders);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  }

  Future<Map<String, dynamic>> put(
    String path, {
    Map<String, dynamic>? body,
    Map<String, dynamic>? data,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final decoded = await _send('PUT', path,
        auth: auth, body: body ?? data, extraHeaders: extraHeaders);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  }

  Future<void> delete(String path) async {
    await _send('DELETE', path, auth: true);
  }

  Future<dynamic> _send(
    String method,
    String path, {
    required bool auth,
    Map<String, dynamic>? body,
    Map<String, String>? extraHeaders,
    bool isRetry = false,
  }) async {
    final uri = Uri.parse('${Env.apiBaseUrl}$path');
    final headers = _headers(auth)..addAll(extraHeaders ?? const {});
    final http.Response response;
    try {
      final request = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) request.body = jsonEncode(body);
      response = await http.Response.fromStream(
          await _client.send(request).timeout(timeout));
    } on SocketException {
      throw const ApiException.network();
    } on TimeoutException {
      throw const ApiException.network();
    } on http.ClientException {
      throw const ApiException.network();
    }

    if (response.statusCode == 401 &&
        auth &&
        !isRetry &&
        onUnauthorized != null) {
      if (await _refreshOnce()) {
        return _send(method, path,
            auth: auth, body: body, extraHeaders: extraHeaders, isRetry: true);
      }
    }
    return _decode(response);
  }

  /// Concurrent 401s share one refresh: a refresh token can be used only once.
  Future<bool> _refreshOnce() {
    return _refreshing ??=
        onUnauthorized!().whenComplete(() => _refreshing = null);
  }

  dynamic _decode(http.Response response) {
    dynamic decoded;
    if (response.body.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        decoded = null;
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException.fromEnvelope(
        response.statusCode,
        decoded is Map<String, dynamic> ? decoded : <String, dynamic>{},
      );
    }
    return decoded;
  }

  void dispose() => _client.close();
}
