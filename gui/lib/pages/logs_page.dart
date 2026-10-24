import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
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
  static const _rowExtent = 22.0;

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

    final bodyStyle = Theme.of(context).textTheme.bodySmall;

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
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.receipt_long_outlined,
                          size: 44, color: Theme.of(context).colorScheme.outline),
                      const SizedBox(height: 10),
                      Text('暂无日志', style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 4),
                      Text('开始学习后，引擎日志会实时出现在这里',
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                )
              // SelectionArea 包整个列表：整页可选文本，但不再为每行
              // 构建 SelectableText（千行日志时是主要卡顿源）。
              : SelectionArea(
                  child: ListView.builder(
                    controller: _controller,
                    padding: const EdgeInsets.all(24),
                    itemCount: filtered.length,
                    itemExtent: _rowExtent,
                    scrollCacheExtent: ScrollCacheExtent.pixels(800),
                    addAutomaticKeepAlives: false,
                    addRepaintBoundaries: true,
                    itemBuilder: (context, index) {
                      final log = filtered[index];
                      return Row(
                        children: [
                          SizedBox(
                            width: 64,
                            child: Text(log.ts, style: bodyStyle),
                          ),
                          SizedBox(
                            width: 72,
                            child: Text(
                              log.level,
                              style: bodyStyle?.copyWith(
                                color: _levelColor(context, log.level),
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                          Expanded(
                            child: Text(
                              log.message,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: bodyStyle,
                            ),
                          ),
                        ],
                      );
                    },
                  ),
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
