import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/engine_client.dart';
import '../core/models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/skeleton.dart';

/// 仪表盘：引擎全流程运行状态的结构化面板。
///
/// 状态标识 + 核心指标卡 + 进度条 + 异常告警 + 活动流，替代原始日志排障；
/// 原始日志仍保留在「日志」页。
class DashboardPage extends ConsumerStatefulWidget {
  const DashboardPage({super.key});

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  final Set<String> _pending = {};

  bool get _busy => _pending.isNotEmpty;

  Future<void> _control(String method) async {
    if (_pending.contains(method)) return; // 防抖
    setState(() => _pending.add(method));
    try {
      await ref.read(engineClientProvider).rpc(method);
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    } finally {
      if (mounted) setState(() => _pending.remove(method));
    }
  }

  Future<void> _start() async {
    if (_pending.contains('study.start')) return;
    final selected = ref.read(selectedCoursesProvider);
    if (selected.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请先在「课程」页选择要学习的课程')),
      );
      return;
    }
    setState(() => _pending.add('study.start'));
    try {
      await ref.read(engineClientProvider).rpc('study.start', {
        'course_ids': selected.toList(),
      });
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    } finally {
      if (mounted) setState(() => _pending.remove('study.start'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = ref.watch(statusProvider);
    final activity = ref.watch(activityProvider);
    final selectedCount = ref.watch(selectedCoursesProvider.select((set) => set.length));

    final skeleton = status.state == 'loading' && status.total == 0 && activity.isEmpty;
    // 最近出错的普通任务（排除整轮 run 级错误），告警条里给出具体条目。
    final recentErrors = [
      for (final item in activity)
        if (item.isError && item.kind != 'run') item,
    ].take(3).toList();

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
          child: Column(
            children: [
              _RunHeader(
                status: status,
                selectedCount: selectedCount,
                busy: _busy,
                pending: _pending,
                onStart: _start,
                onControl: _control,
                skeleton: skeleton,
              ),
              if (!skeleton && (status.failed > 0 || status.state == 'error')) ...[
                const SizedBox(height: 12),
                _AlertStrip(status: status, errors: recentErrors),
              ],
              const SizedBox(height: 12),
              _MetricsGrid(status: status, skeleton: skeleton),
              if (status.bankStats.isNotEmpty) ...[
                const SizedBox(height: 8),
                _BankStatsRow(stats: status.bankStats),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: _ActivityPanel(activities: activity, skeleton: skeleton, status: status),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------ 头部运行卡

class _RunHeader extends StatelessWidget {
  const _RunHeader({
    required this.status,
    required this.selectedCount,
    required this.busy,
    required this.pending,
    required this.onStart,
    required this.onControl,
    required this.skeleton,
  });

  final StudyStatus status;
  final int selectedCount;
  final bool busy;
  final Set<String> pending;
  final VoidCallback onStart;
  final void Function(String method) onControl;
  final bool skeleton;

  @override
  Widget build(BuildContext context) {
    if (skeleton) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(children: [SkeletonBox(width: 88, height: 28, radius: 12), Spacer()]),
              const SizedBox(height: 16),
              SkeletonBox(width: MediaQuery.sizeOf(context).width * 0.4, height: 22),
              const SizedBox(height: 18),
              const SkeletonBox(height: 10, radius: 5),
            ],
          ),
        ),
      );
    }

    final running = status.isRunning;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _StateChip(state: status.state),
                const Spacer(),
                if (!running)
                  FilledButton.icon(
                    onPressed: busy ? null : onStart,
                    icon: pending.contains('study.start')
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.play_arrow),
                    label: Text(selectedCount == 0 ? '开始学习' : '开始学习 ($selectedCount)'),
                  )
                else ...[
                  if (status.state == 'paused')
                    FilledButton.icon(
                      onPressed: busy ? null : () => onControl('study.resume'),
                      icon: const Icon(Icons.play_arrow),
                      label: const Text('继续'),
                    )
                  else
                    OutlinedButton.icon(
                      onPressed: busy || status.state == 'stopping'
                          ? null
                          : () => onControl('study.pause'),
                      icon: const Icon(Icons.pause),
                      label: const Text('暂停'),
                    ),
                  const SizedBox(width: 8),
                  FilledButton.tonalIcon(
                    onPressed: busy || status.state == 'stopping'
                        ? null
                        : () => onControl('study.stop'),
                    icon: const Icon(Icons.stop),
                    label: const Text('停止'),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 16),
            Text(
              status.detail.isEmpty ? '就绪，等待开始学习' : status.detail,
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            // 当前任务快照：类型 + 名称 + 视频进度（运行中才显示）
            if (running && status.current != null && status.current!.kind != 'run') ...[
              const SizedBox(height: 10),
              _CurrentTaskRow(activity: status.current!),
            ],
            const SizedBox(height: 16),
            TweenAnimationBuilder<double>(
              tween: Tween(end: status.total > 0 ? status.progress : 0.0),
              duration: const Duration(milliseconds: 400),
              curve: Curves.easeOutCubic,
              builder: (context, value, child) => ClipRRect(
                borderRadius: BorderRadius.circular(8),
                // 空闲时显示 0 进度轨道而非不定态动画（不定态永不收敛）。
                child: LinearProgressIndicator(
                  value: status.total > 0 ? value : 0.0,
                  minHeight: 10,
                ),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Text(
                  status.total > 0
                      ? '${status.done} / ${status.total} 章节 · ${(status.progress * 100).toStringAsFixed(0)}%'
                      : '尚未开始',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const Spacer(),
                if (status.elapsed > 0)
                  _ElapsedText(base: status.elapsed, running: running),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StateChip extends StatelessWidget {
  const _StateChip({required this.state});

  final String state;

  @override
  Widget build(BuildContext context) {
    final color = statusColor(context, state);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 240),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_stateIcon(state), size: 14, color: color),
          const SizedBox(width: 6),
          Text(
            _stateLabel(state),
            style: TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }

  IconData _stateIcon(String state) => switch (state) {
        'running' => Icons.autorenew,
        'loading' => Icons.downloading,
        'paused' => Icons.pause_circle_outline,
        'stopping' => Icons.stop_circle_outlined,
        'error' => Icons.error_outline,
        _ => Icons.check_circle_outline,
      };

  String _stateLabel(String state) => switch (state) {
        'running' => '学习中',
        'loading' => '准备中',
        'paused' => '已暂停',
        'stopping' => '停止中',
        'error' => '出错',
        _ => '空闲',
      };
}

class _CurrentTaskRow extends StatelessWidget {
  const _CurrentTaskRow({required this.activity});

  final TaskActivity activity;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isMedia = activity.kind == 'video' || activity.kind == 'audio';
    return Row(
      children: [
        Icon(kindIcon(activity.kind), size: 18, color: scheme.primary),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            activity.describe(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ),
        if (isMedia && activity.progress != null)
          Text(
            '${(activity.progress! * 100).toStringAsFixed(0)}%',
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: scheme.primary, fontWeight: FontWeight.w600),
          ),
      ],
    );
  }
}

/// 本地秒表：两次轮询之间自己走秒，只重建这一个文本。
class _ElapsedText extends StatefulWidget {
  const _ElapsedText({required this.base, required this.running});

  final int base;
  final bool running;

  @override
  State<_ElapsedText> createState() => _ElapsedTextState();
}

class _ElapsedTextState extends State<_ElapsedText> {
  Timer? _timer;
  late int _seconds = widget.base;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(covariant _ElapsedText oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 引擎轮询给出权威值时对齐本地秒表。
    if ((widget.base - oldWidget.base).abs() > 1) {
      _seconds = widget.base;
    }
    _start();
  }

  void _start() {
    if (!widget.running) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    _timer ??= Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _seconds += 1);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _format(int total) {
    final h = total ~/ 3600;
    final m = (total % 3600) ~/ 60;
    final s = total % 60;
    final mm = m.toString().padLeft(2, '0');
    final ss = s.toString().padLeft(2, '0');
    return h > 0 ? '$h:$mm:$ss' : '$mm:$ss';
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.timer_outlined,
            size: 14, color: Theme.of(context).colorScheme.outline),
        const SizedBox(width: 4),
        Text('已运行 ${_format(_seconds)}', style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

// ---------------------------------------------------------------- 异常告警条

class _AlertStrip extends StatelessWidget {
  const _AlertStrip({required this.status, required this.errors});

  final StudyStatus status;
  final List<TaskActivity> errors;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final message = status.state == 'error'
        ? (status.detail.isEmpty ? '任务出错，详情见日志' : status.detail)
        : '本轮已有 ${status.failed} 个章节失败，建议到「日志」页排查后重跑';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.warning_amber_rounded, color: scheme.error, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  message,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: scheme.onErrorContainer),
                ),
              ),
            ],
          ),
          if (errors.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final item in errors)
                  Tooltip(
                    message: item.describe(),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: scheme.errorContainer,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(kindIcon(item.kind), size: 12, color: scheme.onErrorContainer),
                          const SizedBox(width: 4),
                          ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 220),
                            child: Text(
                              item.name.isNotEmpty ? item.name : item.describe(),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context)
                                  .textTheme
                                  .labelSmall
                                  ?.copyWith(color: scheme.onErrorContainer),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// 题库分源命中统计条：多题库梯度回退时逐源展示 查询/命中。
class _BankStatsRow extends StatelessWidget {
  const _BankStatsRow({required this.stats});

  final List<BankStat> stats;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final bank in stats)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHigh,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.quiz_outlined, size: 13, color: theme.colorScheme.outline),
                const SizedBox(width: 6),
                Text(bank.name, style: theme.textTheme.labelSmall),
                const SizedBox(width: 8),
                Text(
                  '${bank.hits}/${bank.queries}',
                  style: theme.textTheme.labelSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: bank.queries == 0
                        ? theme.colorScheme.outline
                        : (bank.hitRate ?? 0) >= 0.6
                            ? kSuccessColor
                            : kWarningColor,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

// ------------------------------------------------------------------ 指标卡片

class _MetricsGrid extends StatelessWidget {
  const _MetricsGrid({required this.status, required this.skeleton});

  final StudyStatus status;
  final bool skeleton;

  @override
  Widget build(BuildContext context) {
    if (skeleton) {
      return LayoutBuilder(builder: (context, constraints) {
        final (columns, cardWidth) = _grid(constraints);
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (var i = 0; i < columns; i++)
              SizedBox(
                width: cardWidth,
                height: 104,
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SkeletonBox(width: 20, height: 20, radius: 6),
                        const Spacer(),
                        SkeletonBox(width: 64, height: 20),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        );
      });
    }

    final hit = status.hitRate;
    final cards = [
      _MetricCard(
        label: '章节进度',
        value: status.total > 0 ? '${status.done}/${status.total}' : '—',
        icon: Icons.checklist_outlined,
      ),
      _MetricCard(
        label: '失败章节',
        value: '${status.failed}',
        icon: Icons.error_outline,
        tone: status.failed > 0 ? kErrorColor : null,
      ),
      _MetricCard(
        label: '课程',
        value: status.courses > 0 ? '${status.courses}' : '—',
        icon: Icons.school_outlined,
      ),
      _MetricCard(
        label: '题库命中率',
        value: hit == null ? '—' : '${(hit * 100).toStringAsFixed(0)}%',
        icon: Icons.fact_check_outlined,
        detail: status.tikuQueries > 0 ? '${status.tikuHits}/${status.tikuQueries} 题' : null,
      ),
      _MetricCard(
        label: '题库覆盖率',
        value: status.coverRate == null ? '—' : '${status.coverRate!.toStringAsFixed(0)}%',
        icon: Icons.insights_outlined,
      ),
      _MetricCard(
        label: '最近成绩',
        value: status.lastScore == null ? '—' : '${status.lastScore!.toStringAsFixed(0)} 分',
        icon: Icons.grade_outlined,
        tone: (status.lastScore ?? 100) < 60 ? kWarningColor : null,
      ),
    ];

    return LayoutBuilder(builder: (context, constraints) {
      final (columns, cardWidth) = _grid(constraints);
      return Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          for (final card in cards)
            SizedBox(width: cardWidth, height: 104, child: card),
        ],
      );
    });
  }

  (int, double) _grid(BoxConstraints constraints) {
    const gap = 12.0;
    final columns = (constraints.maxWidth / 200).floor().clamp(2, 6);
    final cardWidth = (constraints.maxWidth - gap * (columns - 1)) / columns;
    return (columns, cardWidth);
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    required this.icon,
    this.tone,
    this.detail,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color? tone;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final accent = tone ?? scheme.primary;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: accent),
                const Spacer(),
                if (detail != null)
                  Flexible(
                    child: Text(
                      detail!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context)
                          .textTheme
                          .labelSmall
                          ?.copyWith(color: scheme.outline),
                    ),
                  ),
              ],
            ),
            const Spacer(),
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 240),
              child: Text(
                value,
                key: ValueKey('$label-$value'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
            ),
            Text(label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}

// -------------------------------------------------------------------- 活动流

class _ActivityPanel extends StatelessWidget {
  const _ActivityPanel({
    required this.activities,
    required this.skeleton,
    required this.status,
  });

  final List<TaskActivity> activities;
  final bool skeleton;
  final StudyStatus status;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.fromLTRB(24, 0, 24, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 12, 8),
            child: Row(
              children: [
                Text('活动流', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(width: 8),
                Text(
                  '实时任务事件 · 原始日志见「日志」页',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: Theme.of(context).colorScheme.outline),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: skeleton
                ? const _ActivitySkeleton()
                : activities.isEmpty
                    ? _EmptyActivity(status: status)
                    : ListView.builder(
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        itemCount: activities.length,
                        itemExtent: 56,
                        scrollCacheExtent: ScrollCacheExtent.pixels(400),
                        addAutomaticKeepAlives: false,
                        itemBuilder: (context, index) =>
                            _ActivityRow(activity: activities[index]),
                      ),
          ),
        ],
      ),
    );
  }
}

class _ActivitySkeleton extends StatelessWidget {
  const _ActivitySkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.all(20),
      itemCount: 5,
      separatorBuilder: (_, _) => const SizedBox(height: 14),
      itemBuilder: (context, index) => Row(
        children: [
          const SkeletonBox(width: 32, height: 32, radius: 16),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SkeletonBox(width: 200 + (index % 3) * 40, height: 13),
                const SizedBox(height: 6),
                SkeletonBox(width: 140, height: 10),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({required this.activity});

  final TaskActivity activity;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (phaseIcon, phaseColor) = _phaseVisual(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: scheme.surfaceContainerHighest,
              shape: BoxShape.circle,
            ),
            child: Icon(kindIcon(activity.kind), size: 17, color: scheme.onSurfaceVariant),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _title(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context)
                      .textTheme
                      .bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                if (activity.kind == 'video' || activity.kind == 'audio')
                  Row(
                    children: [
                      SizedBox(
                        width: 160,
                        child: TweenAnimationBuilder<double>(
                          tween: Tween(end: activity.progress ?? 0),
                          duration: const Duration(milliseconds: 300),
                          builder: (context, value, _) => ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: value.clamp(0.0, 1.0),
                              minHeight: 3,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        TaskActivity.kindLabel(activity.kind),
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: scheme.outline),
                      ),
                    ],
                  )
                else
                  Text(
                    TaskActivity.kindLabel(activity.kind),
                    style: Theme.of(context)
                        .textTheme
                        .bodySmall
                        ?.copyWith(color: scheme.outline),
                  ),
              ],
            ),
          ),
          if (activity.isRetry)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text(
                '第 ${activity.tries ?? '?'} 次',
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: kWarningColor),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(left: 10),
            child: Icon(phaseIcon, size: 18, color: phaseColor),
          ),
        ],
      ),
    );
  }

  String _title() {
    if (activity.phase == 'progress') return activity.describe();
    final verb = switch (activity.phase) {
      'start' => '开始',
      'done' => '完成',
      'error' => '异常',
      'retry' => '重试',
      'stats' => '统计',
      'scored' => '成绩',
      _ => '',
    };
    final subject = activity.name.isNotEmpty
        ? activity.name
        : (activity.chapter.isNotEmpty ? activity.chapter : activity.course);
    final where = activity.course.isNotEmpty && subject != activity.course
        ? '${activity.course} · '
        : '';
    return '$where$verb $subject'.trim();
  }

  (IconData, Color) _phaseVisual(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return switch (activity.phase) {
      'done' || 'finished' => (Icons.check_circle, kSuccessColor),
      'error' => (Icons.error, kErrorColor),
      'retry' => (Icons.refresh, kWarningColor),
      'scored' => (Icons.grade, kWarningColor),
      'stats' => (Icons.insights, scheme.primary),
      _ => (Icons.radio_button_unchecked, scheme.outline),
    };
  }
}

/// 活动流为空时的引导（空闲 / 未选课两种语境）。
class _EmptyActivity extends StatelessWidget {
  const _EmptyActivity({required this.status});

  final StudyStatus status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    // 小窗口下整体可滚动，避免引导内容溢出。
    return SingleChildScrollView(
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 24),
            Icon(
              status.isRunning ? Icons.radar : Icons.space_dashboard_outlined,
              size: 44,
              color: scheme.outline,
            ),
            const SizedBox(height: 10),
            Text(
              status.isRunning ? '等待引擎事件…' : '开始学习后，任务进展会以结构化事件出现在这里',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (!status.isRunning) ...[
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    _GuideStep(order: '1', text: '在「设置」填写账号与题库，保存后写入 config.ini'),
                    _GuideStep(order: '2', text: '在「课程」页刷新并勾选要学习的课程'),
                    _GuideStep(order: '3', text: '回到这里点击「开始学习」，仪表盘实时显示进展'),
                    _GuideStep(order: '4', text: '手动答题会弹出答题窗口，异常可到「日志」页排查'),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

class _GuideStep extends StatelessWidget {
  const _GuideStep({required this.order, required this.text});

  final String order;
  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 18,
            height: 18,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: scheme.primaryContainer,
              shape: BoxShape.circle,
            ),
            child: Text(
              order,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: scheme.onPrimaryContainer,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Flexible(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
        ],
      ),
    );
  }
}

// -------------------------------------------------------------------- 共享

IconData kindIcon(String kind) => switch (kind) {
      'run' => Icons.flag_outlined,
      'chapter' => Icons.auto_stories_outlined,
      'video' => Icons.play_circle_outline,
      'audio' => Icons.graphic_eq,
      'document' => Icons.description_outlined,
      'work' => Icons.quiz_outlined,
      'read' => Icons.menu_book_outlined,
      'live' => Icons.live_tv_outlined,
      _ => Icons.circle_outlined,
    };
