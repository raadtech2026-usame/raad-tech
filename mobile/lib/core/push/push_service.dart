import 'dart:convert';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_state.dart';
import '../network/api_client.dart';
import '../storage/secure_token_storage.dart';

/// Top-level background message handler required by firebase_messaging.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  try {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp();
    }
  } catch (_) {}
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
        await Firebase.initializeApp();
      }

      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);

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
          'Opened app from FCM background notification: ${message.data}',
        );
      });

      // Handle message open from terminated state
      final initialMessage = await FirebaseMessaging.instance
          .getInitialMessage();
      if (initialMessage != null) {
        debugPrint(
          'Opened app from FCM terminated state: ${initialMessage.data}',
        );
      }

      _initialized = true;
    } catch (e) {
      debugPrint(
        'FirebasePushService initialization error (safe fallback): $e',
      );
    }
  }

  @override
  Future<void> register() async {
    try {
      await _ensureInitialized();
      final messaging = FirebaseMessaging.instance;

      // Request notification permissions
      final settings = await messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
        provisional: false,
      );

      if (settings.authorizationStatus == AuthorizationStatus.denied) {
        return;
      }

      final token = await messaging.getToken();
      if (token == null || token.isEmpty) return;

      String platformName = 'android';
      if (!kIsWeb) {
        if (Platform.isIOS) platformName = 'ios';
        if (Platform.isAndroid) platformName = 'android';
      }

      // Register device FCM token with backend POST /notifications/tokens
      final response = await _apiClient.post(
        '/notifications/tokens',
        body: {'fcm_token': token, 'platform': platformName},
      );

      final deviceTokenId = response['id'] as String?;
      if (deviceTokenId != null) {
        await _tokenStorage.saveCustom(_registeredTokenIdKey, deviceTokenId);
      }

      // Listen for FCM token refreshes
      messaging.onTokenRefresh.listen((newToken) async {
        try {
          final res = await _apiClient.post(
            '/notifications/tokens',
            body: {'fcm_token': newToken, 'platform': platformName},
          );
          final newId = res['id'] as String?;
          if (newId != null) {
            await _tokenStorage.saveCustom(_registeredTokenIdKey, newId);
          }
        } catch (_) {}
      });
    } catch (e) {
      debugPrint('FirebasePushService register error: $e');
    }
  }

  @override
  Future<void> unregister() async {
    try {
      final deviceTokenId = await _tokenStorage.readCustom(
        _registeredTokenIdKey,
      );
      if (deviceTokenId != null) {
        try {
          await _apiClient.delete('/notifications/tokens/$deviceTokenId');
        } catch (_) {}
        await _tokenStorage.deleteCustom(_registeredTokenIdKey);
      }
      try {
        await FirebaseMessaging.instance.deleteToken();
      } catch (_) {}
    } catch (e) {
      debugPrint('FirebasePushService unregister error: $e');
    }
  }
}

final pushServiceProvider = Provider<PushService>((ref) {
  return FirebasePushService(
    ref.watch(apiClientProvider),
    ref.watch(secureTokenStorageProvider),
  );
});
