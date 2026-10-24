import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/core/models.dart';
import 'package:fxxxxc/pages/logs_page.dart';
import 'package:fxxxxc/state.dart';

void main() {
  testWidgets('logs page renders entries and filters by level', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(logsProvider.notifier).add(const LogEntry(
          ts: '12:00:01',
          level: 'INFO',
          logger: 'study',
          message: '开始学习课程',
        ));
    container.read(logsProvider.notifier).add(const LogEntry(
          ts: '12:00:02',
          level: 'ERROR',
          logger: 'study',
          message: '章节失败',
        ));

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: Scaffold(body: LogsPage())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('开始学习课程'), findsOneWidget);
    expect(find.text('章节失败'), findsOneWidget);

    await tester.tap(find.widgetWithText(ChoiceChip, 'ERROR'));
    await tester.pumpAndSettle();

    expect(find.text('开始学习课程'), findsNothing);
    expect(find.text('章节失败'), findsOneWidget);
  });
}
