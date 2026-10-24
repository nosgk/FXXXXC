import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state.dart';
import '../theme.dart';

class LogsPage extends ConsumerStatefulWidget {
  const LogsPage({super.key});

  @override
  ConsumerState<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends ConsumerState<LogsPage> {
  String _level = '全部';
  bool _follow = true;
  final _controller = ScrollController();

  static const _levels = ['全部', 'INFO', 'WARNING', 'ERROR'];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final logs = ref.watch(logsProvider);
    final filtered = _level == '全部'
        ? logs
        : logs.where((log) => log.level == _level).toList();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_follow && _controller.hasClients) {
        _controller.jumpTo(_controller.position.maxScrollExtent);
      }
    });

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
          child: Row(
            children: [
              for (final level in _levels) ...[
                ChoiceChip(
                  label: Text(level),
                  selected: _level == level,
                  onSelected: (_) => setState(() => _level = level),
                ),
                const SizedBox(width: 8),
              ],
              const Spacer(),
              IconButton(
                tooltip: _follow ? '暂停自动滚动' : '跟随最新',
                onPressed: () => setState(() => _follow = !_follow),
                icon: Icon(_follow ? Icons.vertical_align_bottom : Icons.pause),
              ),
              IconButton(
                tooltip: '清空显示',
                onPressed: () => ref.read(logsProvider.notifier).clear(),
                icon: const Icon(Icons.delete_sweep_outlined),
              ),
            ],
          ),
        ),
        Expanded(
          child: filtered.isEmpty
              ? Center(
                  child: Text('暂无日志', style: Theme.of(context).textTheme.bodySmall),
                )
              : ListView.builder(
                  controller: _controller,
                  padding: const EdgeInsets.all(24),
                  itemCount: filtered.length,
                  itemBuilder: (context, index) {
                    final log = filtered[index];
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SizedBox(
                            width: 64,
                            child: Text(
                              log.ts,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                          SizedBox(
                            width: 72,
                            child: Text(
                              log.level,
                              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                    color: _levelColor(context, log.level),
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                          ),
                          Expanded(
                            child: SelectableText(
                              log.message,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Color _levelColor(BuildContext context, String level) {
    switch (level) {
      case 'ERROR':
        return kErrorColor;
      case 'WARNING':
        return kWarningColor;
      case 'SUCCESS':
        return kSuccessColor;
      case 'DEBUG':
      case 'TRACE':
        return Theme.of(context).colorScheme.outline;
      default:
        return Theme.of(context).colorScheme.onSurface;
    }
  }
}
