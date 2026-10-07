/// Mirrors the backend's standard error envelope exactly (`.claude/rules/api.md` #4:
/// `{ error: { code, message, correlation_id, details? } }`) — every REST call in this app
/// throws this on a non-2xx response, never a raw `http.Response`, so every screen handles
/// errors the same documented shape the web dashboard already relies on.
class ApiException implements Exception {
  final int statusCode;
  final String code;
  final String message;
  final String? correlationId;

  const ApiException({
    required this.statusCode,
    required this.code,
    required this.message,
    this.correlationId,
  });

  /// The server could not be reached at all (offline, timeout, DNS).
  const ApiException.network()
      : statusCode = 0,
        code = 'NETWORK',
        message = 'Could not reach the RAAD server. Check your connection.',
        correlationId = null;

  bool get isNetwork => statusCode == 0;
  bool get isNotFound => statusCode == 404;
  bool get isUnauthorized => statusCode == 401;

  factory ApiException.fromEnvelope(int statusCode, Map<String, dynamic> body) {
    final error = body['error'] as Map<String, dynamic>?;
    if (error == null) {
      return ApiException(
        statusCode: statusCode,
        code: 'UNKNOWN_ERROR',
        message: 'An unexpected error occurred.',
      );
    }
    return ApiException(
      statusCode: statusCode,
      code: (error['code'] as String?) ?? 'UNKNOWN_ERROR',
      message: (error['message'] as String?) ?? 'An unexpected error occurred.',
      correlationId: error['correlation_id'] as String?,
    );
  }

  @override
  String toString() => 'ApiException($statusCode, $code): $message';
}
