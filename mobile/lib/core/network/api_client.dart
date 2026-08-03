import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/env.dart';
import 'api_exception.dart';

/// Thin REST client: JSON in/out, bearer auth, the standard error envelope
/// (`api_exception.dart`). One instance per app run, holding the current access token in
/// memory only (`setAccessToken`/`clearAccessToken`, called by `AuthController`) — this class
/// never persists anything itself, matching `.claude/rules/flutter.md` #5's "tokens live in
/// secure storage; other state may use local cache" (the *refresh* token is the one that needs
/// secure storage, not this).
class ApiClient {
  final http.Client _client;
  String? _accessToken;

  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  void setAccessToken(String token) => _accessToken = token;

  void clearAccessToken() => _accessToken = null;

  Map<String, String> _headers({bool auth = true}) {
    final headers = {'Content-Type': 'application/json'};
    if (auth && _accessToken != null) {
      headers['Authorization'] = 'Bearer $_accessToken';
    }
    return headers;
  }

  Future<Map<String, dynamic>> get(String path, {bool auth = true}) async {
    final response = await _client.get(
      Uri.parse('${Env.apiBaseUrl}$path'),
      headers: _headers(auth: auth),
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? body,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final headers = _headers(auth: auth);
    if (extraHeaders != null) headers.addAll(extraHeaders);
    final response = await _client.post(
      Uri.parse('${Env.apiBaseUrl}$path'),
      headers: headers,
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(response);
  }

  Map<String, dynamic> _decode(http.Response response) {
    final bodyText = response.body.isEmpty ? '{}' : response.body;
    final decoded = jsonDecode(bodyText);
    final map = decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException.fromEnvelope(response.statusCode, map);
    }
    return map;
  }

  void dispose() => _client.close();
}
