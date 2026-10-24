import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state.dart';
import '../theme.dart';

class TasksPage extends ConsumerWidget {
  const TasksPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(statusProvider);
    final logs = ref.watch(logsProvider);
    final errors = logs.where((log) => log.level == 'ERROR').toList().reversed.take(30).toList();
    final color = statusColor(context, status.state);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('运行概览', style: Theme.of(context).textTheme.titleMedium),
                    const Spacer(),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.14),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(status.state, style: TextStyle(color: color)),
                    ),
                  ],
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
                  '${status.done} / ${status.total} 章节 · 失败 ${status.failed}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (status.detail.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(status.detail, style: Theme.of(context).textTheme.bodyMedium),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('最近错误', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (errors.isEmpty)
                  Text('暂无错误', style: Theme.of(context).textTheme.bodySmall)
                else
                  ...errors.map(
                    (error) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            error.ts,
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          const SizedBox(width: 12),
                          Expanded(child: Text(error.message)),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
