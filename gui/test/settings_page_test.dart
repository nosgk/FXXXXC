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
  // 页面含题库源工作台等内容较长，测试视口拉高避免 ListView 懒加载裁剪掉目标字段。
  tester.view.physicalSize = const Size(1400, 3200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
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

    // 说明文案里也提到「保存配置」，必须精确匹配按钮本身。
    await tester.tap(find.widgetWithText(FilledButton, '保存配置（1 项）'));
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

  testWidgets('bank workbench: expand shows provider fields, drag writes priorities',
      (tester) async {
    final store = <String, dynamic>{
      'tiku': {'submit': 'false'},
      'tiku_bank.a': {
        'enabled': 'true', 'priority': '0', 'name': '言溪',
        'provider': 'TikuYanxi', 'tokens': 'T1',
      },
      'tiku_bank.b': {
        'enabled': 'true', 'priority': '1', 'name': 'AI兜底',
        'provider': 'AI', 'endpoint': 'http://x/v1', 'key': 'k', 'model': 'm',
      },
    };
    final container = await _pump(tester, store);

    // 收起态：只显示摘要；两个实例都在
    expect(find.text('言溪'), findsOneWidget);
    expect(find.text('AI兜底'), findsOneWidget);
    expect(find.text('接口地址 endpoint'), findsNothing);

    // 展开第二个源（AI兜底）→ 显示 AI 专属字段
    await tester.tap(find.byTooltip('展开配置').last);
    await tester.pumpAndSettle();
    expect(find.text('接口地址 endpoint'), findsOneWidget);
    expect(find.text('额外请求参数 extra_body'), findsOneWidget);

    // 拖拽排序：经测试入口触发 onReorderItem 同款回调（手势接线由框架保证）
    final pageState = tester.state<State>(find.byType(SettingsPage));
    (pageState as dynamic).testReorderBanks(1, 0);
    await tester.pumpAndSettle();
    expect(find.text('1'), findsWidgets); // 序号圆标仍在

    await tester.tap(find.widgetWithText(FilledButton, '保存配置（2 项）'));
    await tester.pumpAndSettle();

    final notifier = container.read(configProvider.notifier) as _FakeConfigNotifier;
    expect(notifier.savedPatches, isNotEmpty);
    final patch = notifier.savedPatches.last;
    expect(patch['tiku_bank.a']?['priority'], '1');
    expect(patch['tiku_bank.b']?['priority'], '0');
  });
}
