import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';

import 'core/engine_client.dart';
import 'core/models.dart';
import 'pages/courses_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/logs_page.dart';
import 'pages/settings_page.dart';
import 'pages/tasks_page.dart';
import 'state.dart';
import 'theme.dart';

class FxxxxcApp extends ConsumerWidget {
  const FxxxxcApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    return MaterialApp(
      title: 'FXXXXC',
      debugShowCheckedModeBanner: false,
      theme: buildFxxxxcTheme(Brightness.light, kSeedColor),
      darkTheme: buildFxxxxcTheme(Brightness.dark, kSeedColor),
      themeMode: mode,
      home: const AppShell(),
    );
  }
}

class _Destination {
  const _Destination(this.label, this.icon, this.selectedIcon);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

const _destinations = [
  _Destination('仪表盘', Icons.space_dashboard_outlined, Icons.space_dashboard),
  _Destination('课程', Icons.school_outlined, Icons.school),
  _Destination('任务', Icons.checklist_outlined, Icons.checklist),
  _Destination('日志', Icons.receipt_long_outlined, Icons.receipt_long),
  _Destination('设置', Icons.settings_outlined, Icons.settings),
];

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  int _index = 0;
  final Set<int> _visited = {0};
  bool _exiting = false;

  @override
  void initState() {
    super.initState();
    // First frame paints immediately; only after that do we touch native
    // window APIs and spawn the Python engine. Blocking either before the
    // first frame is what made packaged builds hang as "not responding".
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _initWindow();
      ref.read(connectionProvider.notifier).ensureStarted();
    });
  }

  Future<void> _initWindow() async {
    try {
      await windowManager.ensureInitialized();
      await windowManager.setTitle('FXXXXC');
      await windowManager.setMinimumSize(const Size(1000, 700));
      // Intercept the close button: kill the engine tree before destroying
      // the window, otherwise the Python sidecar outlives the GUI.
      await windowManager.setPreventClose(true);
      windowManager.addListener(_AppWindowListener(_exitApp));
    } catch (error) {
      // Window decoration is cosmetic; never let it break startup.
      debugPrint('window init skipped: $error');
    }
  }

  Future<void> _exitApp() async {
    if (_exiting) return;
    _exiting = true;
    try {
      await ref
          .read(engineClientProvider)
          .stop()
          .timeout(const Duration(seconds: 6));
    } catch (_) {
      // Even if stop fails/times out, still exit — the engine's parent
      // watchdog will clean up after our pid disappears.
    }
    await windowManager.destroy();
  }

  void _select(int index) {
    setState(() {
      _index = index;
      _visited.add(index); // 懒构建 + 保活：未访问过的页面不参与首帧
    });
  }

  Widget _pageFor(int index) {
    const pages = [
      DashboardPage(),
      CoursesPage(),
      TasksPage(),
      LogsPage(),
      SettingsPage(),
    ];
    return KeyedSubtree(key: ValueKey('page-$index'), child: pages[index]);
  }

  @override
  Widget build(BuildContext context) {
    final connection = ref.watch(connectionProvider);

    ref.listen<ManualQueue>(manualProvider, (previous, next) {
      final question = next.current;
      if (question == null) return;
      final previousBatch = previous?.batchId ?? '';
      if (previousBatch != next.batchId || previous?.current == null) {
        showDialog(
          context: context,
          barrierDismissible: false,
          builder: (_) => ManualAnswerDialog(question: question),
        );
      } else if (previous?.index != next.index) {
        Navigator.of(context, rootNavigator: true).pop();
        showDialog(
          context: context,
          barrierDismissible: false,
          builder: (_) => ManualAnswerDialog(question: question),
        );
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: Text(_destinations[_index].label),
        actions: [
          _ConnectionChip(connection: connection),
          const SizedBox(width: 12),
        ],
      ),
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: _index,
            onDestinationSelected: _select,
            labelType: NavigationRailLabelType.all,
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Column(
                children: [
                  CircleAvatar(
                    radius: 16,
                    backgroundColor: Theme.of(context).colorScheme.primaryContainer,
                    child: Icon(
                      Icons.play_lesson,
                      size: 18,
                      color: Theme.of(context).colorScheme.onPrimaryContainer,
                    ),
                  ),
                ],
              ),
            ),
            destinations: [
              for (final destination in _destinations)
                NavigationRailDestination(
                  icon: Icon(destination.icon),
                  selectedIcon: Icon(destination.selectedIcon),
                  label: Text(destination.label),
                ),
            ],
          ),
          VerticalDivider(width: 1),
          Expanded(
            child: connection == ConnState.error
                ? _ErrorPane(onRetry: () => ref.read(connectionProvider.notifier).retry())
                : Stack(
                    children: [
                      for (var i = 0; i < _destinations.length; i++)
                        if (_visited.contains(i))
                          Offstage(
                            offstage: i != _index,
                            // 不再包 _PageFadeIn：包装层的换入换出会让整页元素树
                            // 每次切页都重挂载（卡片重新 initState、滚动位置丢失）。
                            child: TickerMode(
                              enabled: i == _index,
                              child: _pageFor(i),
                            ),
                          ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

/// Bridges window_manager's onWindowClose to the app exit cleanup.
class _AppWindowListener extends WindowListener {
  _AppWindowListener(this.onClose);

  final Future<void> Function() onClose;

  @override
  void onWindowClose() {
    onClose();
  }
}

class _ConnectionChip extends ConsumerWidget {
  const _ConnectionChip({required this.connection});

  final ConnState connection;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scheme = Theme.of(context).colorScheme;
    final (label, color) = switch (connection) {
      ConnState.ready => ('引擎已连接', scheme.primaryContainer),
      ConnState.connecting => ('连接中…', scheme.surfaceContainerHighest),
      ConnState.error => ('引擎未连接', scheme.errorContainer),
    };
    return Chip(
      avatar: Icon(Icons.circle, size: 10, color: color),
      label: Text(label),
      visualDensity: VisualDensity.compact,
    );
  }
}

class _ErrorPane extends StatelessWidget {
  const _ErrorPane({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 48, color: Theme.of(context).colorScheme.error),
          const SizedBox(height: 12),
          Text('无法连接到本地引擎', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(
            'Python 引擎进程启动失败或已退出，请检查安装目录与日志。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 16),
          FilledButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('重试')),
        ],
      ),
    );
  }
}

class ManualAnswerDialog extends ConsumerStatefulWidget {
  const ManualAnswerDialog({super.key, required this.question});

  final ManualQuestion question;

  @override
  ConsumerState<ManualAnswerDialog> createState() => _ManualAnswerDialogState();
}

class _ManualAnswerDialogState extends ConsumerState<ManualAnswerDialog> {
  final _controller = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit(String? answer) async {
    if (_busy) return;
    setState(() => _busy = true);
    final client = ref.read(engineClientProvider);
    try {
      await client.rpc('manual.answer', {
        'batch_id': widget.question.batchId,
        'index': widget.question.index,
        'answer': answer,
      });
      if (mounted) Navigator.of(context, rootNavigator: true).pop();
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final options = widget.question.optionList;
    return AlertDialog(
      title: Text('手动答题 · ${widget.question.typeLabel}'),
      content: SizedBox(
        width: 640,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.question.title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            if (options.isNotEmpty)
              ...options.map(
                (option) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Text(option, style: Theme.of(context).textTheme.bodyMedium),
                ),
              )
            else
              Text('（无选项，直接输入答案）', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            TextField(
              controller: _controller,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: '答案',
                hintText: '例如：A 或 AB，判断题填 正确/错误，回车提交',
              ),
              onSubmitted: _submit,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => _submit(null),
          child: const Text('跳过（随机）'),
        ),
        FilledButton(
          onPressed: _busy ? null : () => _submit(_controller.text),
          child: const Text('提交答案'),
        ),
      ],
    );
  }
}
