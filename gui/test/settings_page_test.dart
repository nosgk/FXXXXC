import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/pages/settings_page.dart';
import 'package:fxxxxc/state.dart';

class _FakeConfigNotifier extends ConfigNotifier {
  Map<String, dynamic> store;
  List<Map<String, Map<String, String>>> savedPatches = [];

  _FakeConfigNotifier(this.store);

  @override
  Future<Map<String, dynamic>> build() async => store;

  @override
  Future<void> save(Map<String, Map<String, String>> patch) async {
    savedPatches.add(patch);
    for (final section in patch.keys) {
      (store[section] ??= {}).addAll(patch[section]!);
    }
    ref.invalidateSelf();
  }
}

Future<ProviderContainer> _pump(WidgetTester tester, Map<String, dynamic> store) async {
  final container = ProviderContainer(
    overrides: [
      configProvider.overrideWith(() => _FakeConfigNotifier(store)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: SettingsPage())),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

TextEditingController _controllerOf(WidgetTester tester, String label) {
  final field = tester.widget<TextField>(
    find.widgetWithText(TextField, label).first,
  );
  return field.controller!;
}

void main() {
  testWidgets('edits mark dirty, save sends the changed key, and edits survive rebuilds',
      (tester) async {
    final store = <String, dynamic>{
      'common': {'jobs': '4'},
    };
    await _pump(tester, store);

    final jobsField = find.widgetWithText(TextField, '并发章节数');
    expect(jobsField, findsOneWidget);
    await tester.enterText(jobsField, '9');
    await tester.pump();
    expect(_controllerOf(tester, '并发章节数').text, '9');
    expect(find.textContaining('保存配置（1 项）'), findsOneWidget);

    // Any number of rebuilds must not wipe the user's in-progress edit.
    await tester.pump();
    expect(_controllerOf(tester, '并发章节数').text, '9');

    await tester.tap(find.textContaining('保存配置'));
    await tester.pumpAndSettle();

    final container = tester
        .element(find.byType(SettingsPage))
        .widget as Widget?; // placeholder to keep analyzer quiet
    expect(container, isNotNull);

    final notifier = ProviderScope.containerOf(
      tester.element(find.byType(SettingsPage)),
    ).read(configProvider.notifier) as _FakeConfigNotifier;
    expect(notifier.savedPatches, [
      {
        'common': {'jobs': '9'},
      }
    ]);
    // After read-back the saved value is canonical and dirty flag cleared.
    expect(_controllerOf(tester, '并发章节数').text, '9');
    expect(find.text('保存配置'), findsOneWidget);
  });

  testWidgets('remote config refresh never overwrites a dirty field', (tester) async {
    final store = <String, dynamic>{
      'common': {'jobs': '4', 'speed': '1.5'},
    };
    final container = await _pump(tester, store);

    await tester.enterText(find.widgetWithText(TextField, '视频倍速'), '2.0');
    await tester.pump();

    // Simulate an engine-side config.changed push for an unrelated key.
    final notifier = container.read(configProvider.notifier) as _FakeConfigNotifier;
    notifier.store = {
      'common': {'jobs': '6', 'speed': '1.5'},
    };
    container.invalidate(configProvider);
    await tester.pumpAndSettle();

    // Dirty field untouched, untouched field refreshed.
    expect(_controllerOf(tester, '视频倍速').text, '2.0');
    expect(_controllerOf(tester, '并发章节数').text, '6');
  });
}
