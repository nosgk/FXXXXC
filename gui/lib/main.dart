import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'theme.dart';

Future<void> main() async {
  // Window/controller init must never run before runApp: waiting on native
  // window callbacks pre-first-frame deadlocks the message pump and Windows
  // reports the app as "not responding". Render first, then configure the
  // window from AppShell's post-frame callback.
  await runZonedGuarded<Future<void>>(
    () async {
      WidgetsFlutterBinding.ensureInitialized();
      runApp(const ProviderScope(child: FxxxxcApp()));
    },
    (error, stack) {
      FlutterError.reportError(FlutterErrorDetails(exception: error, stack: stack));
    },
  );
}

class BootstrapErrorApp extends StatelessWidget {
  const BootstrapErrorApp({super.key, this.error});

  final Object? error;

  @override
  Widget build(BuildContext context) {
    final scheme = buildFxxxxcTheme(Brightness.light, kSeedColor).colorScheme;
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildFxxxxcTheme(Brightness.light, kSeedColor),
      home: Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline, size: 48, color: scheme.error),
              const SizedBox(height: 12),
              const Text('启动失败'),
              const SizedBox(height: 8),
              Text('$error', textAlign: TextAlign.center),
            ],
          ),
        ),
      ),
    );
  }
}
