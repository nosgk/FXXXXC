import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/core/models.dart';
import 'package:fxxxxc/pages/dashboard_page.dart';
import 'package:fxxxxc/state.dart';
import 'package:fxxxxc/widgets/skeleton.dart';

void main() {
  Future<ProviderContainer> pumpDashboard(WidgetTester tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    // 应用窗口最小 1000x700；看板在极矮视口会自适应收起头尾，测试用真实尺寸。
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: Scaffold(body: DashboardPage())),
      ),
    );
    await tester.pumpAndSettle();
    return container;
  }

  testWidgets('idle dashboard shows guide and start button', (tester) async {
    await pumpDashboard(tester);

    // 状态芯片与活动流标题
    expect(find.text('空闲'), findsWidgets);
    expect(find.textContaining('开始学习'), findsWidgets);
    expect(find.text('课程看板'), findsOneWidget);
    // 空态引导四步
    expect(find.text('在「课程」页刷新并勾选要学习的课程'), findsOneWidget);
  });

  testWidgets('running dashboard shows progress, metrics and activity feed', (tester) async {
    final container = await pumpDashboard(tester);

    container.read(statusProvider.notifier).replace(const StudyStatus(
          state: 'running',
          detail: '共 4 个章节',
          total: 4,
          done: 1,
          failed: 1,
          courses: 2,
          elapsed: 65,
        ));
    container.read(activityProvider.notifier).addAll([
      TaskActivity(
          kind: 'chapter',
          phase: 'start',
          course: '高等数学',
          chapter: '第一章',
          atTs: DateTime(2026, 1, 1)),
      TaskActivity(
          kind: 'video',
          phase: 'done',
          name: '1.1 导论.mp4',
          course: '高等数学',
          progress: 1.0,
          atTs: DateTime(2026, 1, 1)),
    ]);
    await tester.pumpAndSettle();

    expect(find.text('学习中'), findsOneWidget);
    expect(find.text('1/4'), findsOneWidget); // 章节进度卡
    expect(find.text('1'), findsWidgets); // 失败章节卡等
    expect(find.textContaining('1 / 4 章节'), findsOneWidget);
    // 最新动态条：完成 + 课程名
    expect(find.textContaining('完成 1.1 导论.mp4'), findsOneWidget);
    expect(find.text('最新动态'), findsOneWidget);
    expect(find.textContaining('高等数学'), findsWidgets);
    // 暂停/停止控制可用
    expect(find.widgetWithText(OutlinedButton, '暂停'), findsOneWidget);
    expect(find.text('停止'), findsOneWidget);
  });

  testWidgets('error state shows alert strip', (tester) async {
    final container = await pumpDashboard(tester);

    container.read(statusProvider.notifier).replace(
          const StudyStatus(state: 'error', detail: '登录失败', failed: 0),
        );
    await tester.pumpAndSettle();

    expect(find.textContaining('登录失败'), findsWidgets); // 头部详情 + 告警条
    expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
  });

  testWidgets('loading with no data shows skeleton blocks', (tester) async {
    final container = await pumpDashboard(tester);

    container.read(statusProvider.notifier).replace(const StudyStatus(state: 'loading'));
    await tester.pump();

    // 骨架屏期间没有真实指标卡文本
    expect(find.text('章节进度'), findsNothing);
    expect(find.byType(SkeletonBox), findsWidgets);
  });

  testWidgets('applyTask keeps live snapshot and work stats', (tester) async {
    final container = await pumpDashboard(tester);
    final status = container.read(statusProvider.notifier);

    status.applyTask(const TaskActivity(
        kind: 'video', phase: 'progress', name: '1.1.mp4', progress: 0.5));
    status.applyTask(const TaskActivity(
        kind: 'work',
        phase: 'stats',
        name: 'work-9',
        coverRate: 90,
        message: null));
    status.applyTask(const TaskActivity(
        kind: 'work', phase: 'scored', name: 'work-9', score: 88));

    final state = container.read(statusProvider);
    expect(state.current!.kind, 'work');
    expect(state.coverRate, closeTo(90, 0.01));
    expect(state.lastScore, closeTo(88, 0.01));
  });

  testWidgets('activity feed is capped at 80 entries', (tester) async {
    final container = await pumpDashboard(tester);
    container.read(activityProvider.notifier).addAll([
      for (var i = 0; i < 100; i++)
        TaskActivity(kind: 'chapter', phase: 'start', name: '章$i', atTs: DateTime(2026, 1, 1)),
    ]);
    await tester.pumpAndSettle();

    final activities = container.read(activityProvider);
    expect(activities.length, 80);
    expect(activities.first.name, '章99'); // 最新在前
  });
}
