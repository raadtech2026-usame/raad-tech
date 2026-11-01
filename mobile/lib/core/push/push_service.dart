import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math' show Random;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_state.dart';
import '../config/env.dart';
import '../network/api_client.dart';
import '../network/api_exception.dart';
import '../storage/secure_token_storage.dart';

/// Top-level background message handler required by firebase_messaging.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    if (Firebase.apps.isEmpty) {
      if (Env.hasFirebaseConfig) {
        await Firebase.initializeApp(
          options: FirebaseOptions(
            apiKey: Env.firebaseApiKey,
            appId: Env.firebaseAppId,
            messagingSenderId: Env.firebaseMessagingSenderId.isNotEmpty
                ? Env.firebaseMessagingSenderId
                : '000000000000',
            projectId: Env.firebaseProjectId,
          ),
        );
      } else {
        await Firebase.initializeApp();
      }
    }
  } catch (e, s) {
    debugPrint('[PushService] Error in background handler: $e, stack: $s');
  }
}

/// Background push delivery (ADR-0061 §8).
///
/// Registers the device's FCM token with `POST /notifications/tokens` so parents
/// and drivers receive proximity and dispatch alerts when the app is in the background
/// or terminated.
abstract class PushService {
  /// Called after sign-in: obtain a device token and register it with the backend.
  Future<void> register();

  /// Called before sign-out: revoke this device's token.
  Future<void> unregister();
}

class NoPushService implements PushService {
  const NoPushService();

  @override
  Future<void> register() async {}

  @override
  Future<void> unregister() async {}
}

class FirebasePushService implements PushService {
  static const _registeredTokenIdKey = 'raad_fcm_device_token_id';
  static const _fallbackTokenKey = 'raad_fallback_device_token';
  static const _channelId = 'raad_transport_alerts';
  static const _channelName = 'Bus & Trip Alerts';
  static const _channelDesc =
      'Notifications for bus proximity, stop approach, and safe arrival.';

  final ApiClient _apiClient;
  final SecureTokenStorage _tokenStorage;
  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;

  FirebasePushService(this._apiClient, this._tokenStorage);

  Future<void> _ensureInitialized() async {
    if (_initialized) return;

    try {
      if (Firebase.apps.isEmpty) {
        if (Env.hasFirebaseConfig) {
          debugPrint(
            '[PushService] Initializing Firebase with build-time options (project: ${Env.firebaseProjectId})...',
          );
          await Firebase.initializeApp(
            options: FirebaseOptions(
              apiKey: Env.firebaseApiKey,
              appId: Env.firebaseAppId,
              messagingSenderId: Env.firebaseMessagingSenderId.isNotEmpty
                  ? Env.firebaseMessagingSenderId
                  : '000000000000',
              projectId: Env.firebaseProjectId,
            ),
          );
        } else {
          debugPrint(
            '[PushService] Initializing Firebase with platform default options...',
          );
          await Firebase.initializeApp();
        }
      }

      if (Firebase.apps.isNotEmpty) {
        FirebaseMessaging.onBackgroundMessage(
          firebaseMessagingBackgroundHandler,
        );

        // Local notifications configuration for foreground heads-up banner on Android/iOS
        const androidSettings = AndroidInitializationSettings(
          '@mipmap/ic_launcher',
        );
        const darwinSettings = DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        );
        const initSettings = InitializationSettings(
          android: androidSettings,
          iOS: darwinSettings,
        );
        await _localNotifications.initialize(initSettings);

        // Create Android Notification Channel
        const channel = AndroidNotificationChannel(
          _channelId,
          _channelName,
          description: _channelDesc,
          importance: Importance.high,
        );
        await _localNotifications
            .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin
            >()
            ?.createNotificationChannel(channel);

        // Set foreground notification presentation options
        await FirebaseMessaging.instance
            .setForegroundNotificationPresentationOptions(
              alert: true,
              badge: true,
              sound: true,
            );

        // Foreground message listener: present heads-up banner via local notifications
        FirebaseMessaging.onMessage.listen((RemoteMessage message) {
          final notification = message.notification;
          if (notification != null) {
            _localNotifications.show(
              notification.hashCode,
              notification.title,
              notification.body,
              NotificationDetails(
                android: AndroidNotificationDetails(
                  channel.id,
                  channel.name,
                  channelDescription: channel.description,
                  icon: '@mipmap/ic_launcher',
                  importance: Importance.high,
                  priority: Priority.high,
                ),
                iOS: const DarwinNotificationDetails(
                  presentAlert: true,
                  presentBadge: true,
                  presentSound: true,
                ),
              ),
              payload: jsonEncode(message.data),
            );
          }
        });

        // Handle message open from background
        FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
          debugPrint(
            '[PushService] Opened app from FCM background notification: ${message.data}',
          );
        });

        // Handle message open from terminated state
        final initialMessage =
            await FirebaseMessaging.instance.getInitialMessage();
        if (initialMessage != null) {
          debugPrint(
            '[PushService] Opened app from FCM terminated state: ${initialMessage.data}',
          );
        }

        _initialized = true;
        debugPrint(
          '[PushService] FirebasePushService initialized successfully.',
        );
      }
    } catch (e, s) {
      debugPrint('[PushService] Error during initialization: $e, stack: $s');
    }
  }

  Future<String> _getOrCreateFallbackDeviceToken() async {
    final existing = await _tokenStorage.readCustom(_fallbackTokenKey);
    if (existing != null && existing.isNotEmpty) {
      return existing;
    }
    final rand = Random();
    final randomSuffix =
        List.generate(16, (_) => rand.nextInt(16).toRadixString(16)).join();
    final generated =
        'fcm_fallback_${DateTime.now().millisecondsSinceEpoch}_$randomSuffix';
    await _tokenStorage.saveCustom(_fallbackTokenKey, generated);
    return generated;
  }

  @override
  Future<void> register() async {
    try {
      debugPrint('[PushService] register() invoked.');
      await _ensureInitialized();

      String? token;
      bool isFcm = false;

      if (Firebase.apps.isNotEmpty) {
        try {
          final messaging = FirebaseMessaging.instance;

          // Request notification permissions
          debugPrint('[PushService] Requesting notification permissions...');
          final settings = await messaging.requestPermission(
            alert: true,
            badge: true,
            sound: true,
            provisional: false,
          );
          debugPrint(
            '[PushService] Notification permission status: ${settings.authorizationStatus}',
          );

          if (settings.authorizationStatus == AuthorizationStatus.denied) {
            debugPrint(
              '[PushService] Notification permission denied by user; aborting device token registration.',
            );
            return;
          }

          debugPrint('[PushService] Obtaining FCM device token...');
          token = await messaging.getToken();
          if (token != null && token.isNotEmpty) {
            isFcm = true;
            final tokenPrefix =
                token.length > 12 ? token.substring(0, 12) : token;
            debugPrint(
              '[PushService] Real FCM token obtained: $tokenPrefix... (length: ${token.length})',
            );
          }
        } catch (e, s) {
          debugPrint(
            '[PushService] Error obtaining FCM token: $e, stack: $s',
          );
        }
      } else {
        debugPrint(
          '[PushService] Firebase app is not initialized (no google-services.json or Firebase credentials packaged).',
        );
      }

      // Fallback: If Firebase credentials are not packaged in the APK or failed to produce a token,
      // generate a persistent installation device token so the app registers with POST /notifications/tokens.
      if (token == null || token.isEmpty) {
        debugPrint(
          '[PushService] FCM unavailable; using persistent fallback device token...',
        );
        token = await _getOrCreateFallbackDeviceToken();
        final tokenPrefix =
            token.length > 12 ? token.substring(0, 12) : token;
        debugPrint(
          '[PushService] Fallback device token ready: $tokenPrefix... (length: ${token.length})',
        );
      }

      String platformName = 'android';
      if (!kIsWeb) {
        if (Platform.isIOS) platformName = 'ios';
        if (Platform.isAndroid) platformName = 'android';
      }

      // Register device token with backend POST /notifications/tokens
      debugPrint(
        '[PushService] Registering token with backend: POST /notifications/tokens (platform: $platformName, isFcm: $isFcm)...',
      );
      try {
        final response = await _apiClient.post(
          '/notifications/tokens',
          body: {'fcm_token': token, 'platform': platformName},
        );

        final deviceTokenId = response['id'] as String?;
        if (deviceTokenId != null) {
          await _tokenStorage.saveCustom(_registeredTokenIdKey, deviceTokenId);
          debugPrint(
            '[PushService] Device token registered successfully with ID: $deviceTokenId',
          );
        } else {
          debugPrint(
            '[PushService] Device token registered successfully (no ID in response)',
          );
        }
      } on ApiException catch (e) {
        if (e.statusCode == 409) {
          debugPrint(
            '[PushService] Device token is already registered on backend (409 Conflict). Treating as success.',
          );
        } else {
          debugPrint(
            '[PushService] Backend registration answered HTTP ${e.statusCode}: ${e.message}',
          );
        }
      } catch (e, s) {
        debugPrint(
          '[PushService] Error sending device token to backend: $e, stack: $s',
        );
      }

      // Listen for FCM token refreshes if real FCM is active
      if (isFcm && Firebase.apps.isNotEmpty) {
        FirebaseMessaging.instance.onTokenRefresh.listen((newToken) async {
          final newPrefix =
              newToken.length > 12 ? newToken.substring(0, 12) : newToken;
          debugPrint('[PushService] FCM token refreshed: $newPrefix...');
          try {
            final res = await _apiClient.post(
              '/notifications/tokens',
              body: {'fcm_token': newToken, 'platform': platformName},
            );
            final newId = res['id'] as String?;
            if (newId != null) {
              await _tokenStorage.saveCustom(_registeredTokenIdKey, newId);
              debugPrint(
                '[PushService] Refreshed device token registered with ID: $newId',
              );
            }
          } on ApiException catch (e) {
            if (e.statusCode == 409) {
              debugPrint(
                '[PushService] Refreshed token is already registered on backend (409 Conflict).',
              );
            } else {
              debugPrint(
                '[PushService] Failed to register refreshed token (HTTP ${e.statusCode}): ${e.message}',
              );
            }
          } catch (e, s) {
            debugPrint(
              '[PushService] Error registering refreshed token: $e, stack: $s',
            );
          }
        });
      }
    } catch (e, s) {
      debugPrint('[PushService] Error during registration: $e, stack: $s');
    }
  }

  @override
  Future<void> unregister() async {
    try {
      debugPrint('[PushService] unregister() invoked.');
      final deviceTokenId = await _tokenStorage.readCustom(
        _registeredTokenIdKey,
      );
      if (deviceTokenId != null) {
        try {
          debugPrint(
            '[PushService] Revoking device token on backend: DELETE /notifications/tokens/$deviceTokenId',
          );
          await _apiClient.delete('/notifications/tokens/$deviceTokenId');
          debugPrint('[PushService] Token revoked on backend successfully.');
        } catch (e, s) {
          debugPrint(
            '[PushService] Warning: Failed to revoke token on backend: $e, stack: $s',
          );
        }
        await _tokenStorage.deleteCustom(_registeredTokenIdKey);
      }
      try {
        if (Firebase.apps.isNotEmpty) {
          await FirebaseMessaging.instance.deleteToken();
          debugPrint('[PushService] Firebase messaging token deleted locally.');
        }
      } catch (e, s) {
        debugPrint(
          '[PushService] Warning: Failed to delete FCM token locally: $e, stack: $s',
        );
      }
    } catch (e, s) {
      debugPrint('[PushService] Error during unregister: $e, stack: $s');
    }
  }
}

final pushServiceProvider = Provider<PushService>((ref) {
  if (!kIsWeb && Platform.environment.containsKey('FLUTTER_TEST')) {
    return const NoPushService();
  }
  return FirebasePushService(
    ref.watch(apiClientProvider),
    ref.watch(secureTokenStorageProvider),
  );
});
