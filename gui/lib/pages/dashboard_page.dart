import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/engine_client.dart';
import '../state.dart';
import '../theme.dart';

class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  Future<void> _control(
    WidgetRef ref,
    BuildContext context,
    String method,
  ) async {
    try {
      await ref.read(engineClientProvider).rpc(method);
    } on EngineException catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<void> _start(BuildContext context, WidgetRef ref) async {
    final selected = ref.read(selectedCoursesProvider);
    if (selected.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请先在「课程」页选择要学习的课程')),
      );
      return;
    }
    try {
      await ref.read(engineClientProvider).rpc('study.start', {
        'course_ids': selected.toList(),
      });
    } on EngineException catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(statusProvider);
    final selected = ref.watch(selectedCoursesProvider);
    final running = status.state == 'running' || status.state == 'loading' || status.state == 'paused';
    final color = statusColor(context, status.state);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.14),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        _stateLabel(status.state),
                        style: TextStyle(color: color, fontWeight: FontWeight.w600),
                      ),
                    ),
                    const Spacer(),
                    if (!running)
                      FilledButton.icon(
                        onPressed: () => _start(context, ref),
                        icon: const Icon(Icons.play_arrow),
                        label: Text(selected.isEmpty ? '开始学习' : '开始学习 (${selected.length})'),
                      )
                    else ...[
                      if (status.state == 'paused')
                        FilledButton.icon(
                          onPressed: () => _control(ref, context, 'study.resume'),
                          icon: const Icon(Icons.play_arrow),
                          label: const Text('继续'),
                        )
                      else
                        OutlinedButton.icon(
                          onPressed: () => _control(ref, context, 'study.pause'),
                          icon: const Icon(Icons.pause),
                          label: const Text('暂停'),
                        ),
                      const SizedBox(width: 8),
                      FilledButton.tonalIcon(
                        onPressed: () => _control(ref, context, 'study.stop'),
                        icon: const Icon(Icons.stop),
                        label: const Text('停止'),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 20),
                Text(
                  status.detail.isEmpty ? '就绪，等待开始学习' : status.detail,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: LinearProgressIndicator(
                    value: status.total > 0 ? status.progress : null,
                    minHeight: 10,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  status.total > 0
                      ? '${status.done} / ${status.total} 章节'
                      : '尚未开始',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            _StatCard(label: '课程', value: '${status.courses}', icon: Icons.school_outlined),
            const SizedBox(width: 12),
            _StatCard(label: '章节', value: '${status.total}', icon: Icons.menu_book_outlined),
            const SizedBox(width: 12),
            _StatCard(label: '已完成', value: '${status.done}', icon: Icons.task_alt_outlined),
            const SizedBox(width: 12),
            _StatCard(
              label: '失败',
              value: '${status.failed}',
              icon: Icons.error_outline,
              tone: status.failed > 0 ? kErrorColor : null,
            ),
          ],
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('使用提示', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                const Text('1. 在「设置」中填写账号与题库配置，保存后自动写入 config.ini。'),
                const Text('2. 在「课程」页刷新并勾选要学习的课程。'),
                const Text('3. 回到这里点击「开始学习」，任务会以多线程方式推进。'),
                const Text('4. 遇到手动答题时会弹出答题窗口，跳过则按随机答案处理。'),
              ],
            ),
          ),
        ),
      ],
    );
  }

  String _stateLabel(String state) {
    switch (state) {
      case 'running':
        return '学习中';
      case 'loading':
        return '准备中';
      case 'paused':
        return '已暂停';
      case 'stopping':
        return '停止中';
      case 'error':
        return '出错';
      default:
        return '空闲';
    }
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.label,
    required this.value,
    required this.icon,
    this.tone,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Expanded(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Icon(icon, color: tone ?? scheme.primary),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(value, style: Theme.of(context).textTheme.titleLarge),
                  Text(label, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
