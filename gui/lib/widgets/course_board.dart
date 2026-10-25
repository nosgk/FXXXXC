import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/skeleton.dart';

/// 三栏课程看板（活动流的重设计）：进行中 / 待进行 / 已完成。
///
/// 运行中按引擎分课程进度实时分栏（45 秒内有活动或为当前任务的课程算“进行中”）；
/// 空闲时按选中课程 + 章节明细（course.detail 仓库）分栏。
/// 底部保留一条“最新动态”紧凑条，原始流水仍在「日志」页。
class CourseBoardPanel extends ConsumerWidget {
  const CourseBoardPanel({super.key, required this.status, required this.skeleton});

  final StudyStatus status;
  final bool skeleton;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (skeleton) {
      return Card(
        margin: const EdgeInsets.fromLTRB(24, 0, 24, 24),
        clipBehavior: Clip.antiAlias,
        child: const _BoardSkeleton(),
      );
    }

    final activity = ref.watch(activityProvider);
    final courses = ref.watch(coursesProvider).value ?? const <Course>[];
    final details = ref.watch(courseDetailStoreProvider);
    final selected = ref.watch(selectedCoursesProvider);

    final entries =
        buildBoardEntries(status, activity, courses, details, selected);
    final active = entries
        .where((entry) => entry.column == BoardColumnKind.active)
        .toList();
    final pending = entries
        .where((entry) => entry.column == BoardColumnKind.pending)
        .toList();
    final done =
        entries.where((entry) => entry.column == BoardColumnKind.done).toList();
    final theme = Theme.of(context);

    return Card(
      margin: const EdgeInsets.fromLTRB(24, 0, 24, 24),
      clipBehavior: Clip.antiAlias,
      // 高度自适应：极小视口（如小窗口/测试环境）下收起固定头尾，避免溢出。
      child: LayoutBuilder(builder: (context, constraints) {
        final showHeader = constraints.maxHeight >= 150;
        final showStrip = constraints.maxHeight >= 200;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (showHeader) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
                child: Row(
                  children: [
                    Text('课程看板', style: theme.textTheme.titleMedium),
                    const SizedBox(width: 8),
                    Text(
                      '每门课程的任务与进度 · 运行时自动分栏',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
            ],
            Expanded(
              child: entries.isEmpty
                  ? _BoardEmptyGuide(running: status.isRunning)
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          child: _BoardColumn(
                            title: '进行中',
                            icon: Icons.play_circle_outline,
                            color: theme.colorScheme.primary,
                            entries: active,
                          ),
                        ),
                        const VerticalDivider(width: 1),
                        Expanded(
                          child: _BoardColumn(
                            title: '待进行',
                            icon: Icons.schedule_outlined,
                            color: theme.colorScheme.outline,
                            entries: pending,
                          ),
                        ),
                        const VerticalDivider(width: 1),
                        Expanded(
                          child: _BoardColumn(
                            title: '已完成',
                            icon: Icons.check_circle_outline,
                            color: theme.colorScheme.tertiary,
                            entries: done,
                          ),
                        ),
                      ],
                    ),
            ),
            if (showStrip) _RecentStrip(activity: activity),
          ],
        );
      }),
    );
  }
}

enum BoardColumnKind { active, pending, done }

/// 自带 ScrollController 的滚动条容器：多个纵向滚动视图并存时
/// 不允许共用 PrimaryScrollController，各自持有控制器即可。
class AutoScrollbar extends StatefulWidget {
  const AutoScrollbar({super.key, required this.viewBuilder});

  /// 用回传的 controller 构建滚动视图（ListView/SingleChildScrollView），
  /// 保证滚动条与唯一 ScrollPosition 绑定。
  final Widget Function(ScrollController controller) viewBuilder;

  @override
  State<AutoScrollbar> createState() => _AutoScrollbarState();
}

class _AutoScrollbarState extends State<AutoScrollbar> {
  final ScrollController _controller = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scrollbar(
      controller: _controller,
      thumbVisibility: true,
      child: widget.viewBuilder(_controller),
    );
  }
}

class BoardEntry {
  const BoardEntry({
    required this.courseId,
    required this.title,
    required this.done,
    required this.total,
    required this.failed,
    required this.column,
    this.current,
    this.last,
    this.detail,
    this.activity = const [],
  });

  final String courseId;
  final String title;
  final int done;
  final int total;
  final int failed;
  final BoardColumnKind column;
  /// 引擎当前正在处理的任务（仅“进行中”列）。
  final TaskActivity? current;
  /// 该课程最近一条任务事件（任意列）。
  final TaskActivity? last;
  /// 章节明细（course.detail 仓库；空闲/已读取时可用）。
  final CourseDetail? detail;
  /// 该课程的近期任务事件（展开详情用，最新在前）。
  final List<TaskActivity> activity;

  double? get progress =>
      total <= 0 ? null : (done / total).clamp(0.0, 1.0);
}

/// 组装看板条目：优先用本轮运行的分课程进度；空闲回退到
/// 选中课程 + 章节明细（course.detail 仓库，读一次语义）。
@visibleForTesting
List<BoardEntry> buildBoardEntries(
  StudyStatus status,
  List<TaskActivity> activity,
  List<Course> courses,
  Map<String, AsyncValue<CourseDetail>> details,
  Set<String> selected, {
  DateTime? now,
}) {
  now ??= DateTime.now();
  // 每门课程最近一条事件（活动流最新在前，取首个命中）
  final lastByCourse = <String, TaskActivity>{};
  for (final item in activity) {
    if (item.kind == 'run') continue;
    final key = item.courseId.isNotEmpty
        ? 'id:${item.courseId}'
        : 'title:${item.course}';
    lastByCourse.putIfAbsent(key, () => item);
  }

  final currentId = status.current?.courseId ?? '';
  final entries = <BoardEntry>[];
  final courseById = {for (final course in courses) course.courseId: course};

  if (status.progressByCourse.isNotEmpty) {
    for (final progress in status.coursesProgress) {
      final last = lastByCourse['id:${progress.courseId}'];
      final course = courseById[progress.courseId];
      final detail =
          course == null ? null : details[course.detailKey]?.value;
      final completed = progress.total > 0 && progress.done >= progress.total;
      final recent =
          last?.atTs != null && now.difference(last!.atTs!).inSeconds < 45;
      final isCurrent = progress.courseId == currentId;
      final kind = completed
          ? BoardColumnKind.done
          : (isCurrent || recent)
              ? BoardColumnKind.active
              : BoardColumnKind.pending;
      entries.add(BoardEntry(
        courseId: progress.courseId,
        title: progress.title.isEmpty ? progress.courseId : progress.title,
        done: progress.done,
        total: progress.total,
        failed: progress.failed,
        column: kind,
        current: isCurrent ? status.current : null,
        last: last,
        detail: detail,
        activity: [
          for (final item in activity)
            if (item.courseId == progress.courseId ||
                (item.courseId.isEmpty && item.course == progress.title))
              item,
        ],
      ));
    }
    return entries;
  }

  // 空闲 / 无运行数据：选中课程 + 章节明细
  for (final course in courses) {
    if (!selected.contains(course.courseId)) continue;
    final detail = details[course.detailKey]?.value;
    final doneCount = detail?.finished ?? 0;
    final totalCount = detail?.total ?? 0;
    final completed = totalCount > 0 && doneCount >= totalCount;
    entries.add(BoardEntry(
      courseId: course.courseId,
      title: course.title,
      done: doneCount,
      total: totalCount,
      failed: 0,
      column: completed ? BoardColumnKind.done : BoardColumnKind.pending,
      current: null,
      last: lastByCourse['id:${course.courseId}'],
      detail: detail,
      activity: [
        for (final item in activity)
          if (item.courseId == course.courseId) item,
      ],
    ));
  }
  return entries;
}

class _BoardColumn extends StatelessWidget {
  const _BoardColumn({
    required this.title,
    required this.icon,
    required this.color,
    required this.entries,
  });


  final String title;
  final IconData icon;
  final Color color;
  final List<BoardEntry> entries;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
          child: Row(
            children: [
              Icon(icon, size: 15, color: color),
              const SizedBox(width: 6),
              Text(title,
                  style: theme.textTheme.labelLarge
                      ?.copyWith(color: color, fontWeight: FontWeight.w700)),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Text('${entries.length}',
                    style: theme.textTheme.labelSmall?.copyWith(color: color)),
              ),
            ],
          ),
        ),
        Expanded(
          child: entries.isEmpty
              ? Center(
                  child: Text('暂无',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline)),
                )
              : AutoScrollbar(
                  viewBuilder: (controller) => ListView.builder(
                    controller: controller,
                    padding: const EdgeInsets.fromLTRB(10, 2, 10, 12),
                    itemCount: entries.length,
                    addAutomaticKeepAlives: false,
                    itemBuilder: (context, index) =>
                        _BoardCard(entry: entries[index]),
                  ),
                ),
        ),
      ],
    );
  }
}

class _BoardCard extends StatefulWidget {
  const _BoardCard({required this.entry});

  final BoardEntry entry;

  @override
  State<_BoardCard> createState() => _BoardCardState();
}

class _BoardCardState extends State<_BoardCard> {
  bool _expanded = false;

  BoardEntry get entry => widget.entry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final isDone = entry.column == BoardColumnKind.done;
    final isActive = entry.column == BoardColumnKind.active;

    final TaskActivity? task =
        isActive ? (entry.current ?? entry.last) : entry.last;
    final String taskLine;
    if (task != null) {
      taskLine = activityTitle(task);
    } else if (isDone) {
      taskLine = '全部章节完成';
    } else if (entry.total > 0) {
      taskLine = '等待开始';
    } else {
      taskLine = '章节状态未读取';
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isActive
            ? scheme.primaryContainer.withValues(alpha: 0.35)
            : scheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(12),
        border: isActive
            ? Border.all(color: scheme.primary.withValues(alpha: 0.45))
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Row(
              children: [
                Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                    size: 18, color: scheme.outline),
                const SizedBox(width: 4),
                Text('详情',
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: scheme.outline)),
                const Spacer(),
                if (entry.detail?.score != null)
                  Text('成绩 ${entry.detail!.score!.toStringAsFixed(0)}',
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: scheme.outline)),
                if (entry.detail?.learnCount != null) ...[
                  const SizedBox(width: 8),
                  Text(
                    '学习次数 ${entry.detail!.learnCount}'
                    '${entry.detail!.learnTarget != null ? '/${entry.detail!.learnTarget}' : ''}',
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: scheme.outline),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: Text(
                  entry.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall,
                ),
              ),
              if (entry.total > 0)
                Text(
                  '${entry.done}/${entry.total}',
                  style: theme.textTheme.labelSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: isDone
                        ? scheme.tertiary
                        : (isActive ? scheme.primary : scheme.outline),
                  ),
                ),
              if (entry.failed > 0) ...[
                const SizedBox(width: 6),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(
                    color: scheme.errorContainer.withValues(alpha: 0.7),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text('失败${entry.failed}',
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: scheme.onErrorContainer)),
                ),
              ],
            ],
          ),
          if (entry.progress != null) ...[
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: TweenAnimationBuilder<double>(
                tween: Tween(end: entry.progress),
                duration: const Duration(milliseconds: 300),
                builder: (context, value, _) => LinearProgressIndicator(
                  value: value.clamp(0.0, 1.0),
                  minHeight: 4,
                  color: isDone ? scheme.tertiary : scheme.primary,
                  backgroundColor:
                      scheme.surfaceContainerHighest.withValues(alpha: 0.7),
                ),
              ),
            ),
          ],
          const SizedBox(height: 7),
          Row(
            children: [
              Icon(
                task != null ? boardKindIcon(task.kind) : Icons.more_horiz,
                size: 13,
                color: scheme.outline,
              ),
              const SizedBox(width: 5),
              Expanded(
                child: Text(
                  taskLine,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: scheme.onSurfaceVariant),
                ),
              ),
            ],
          ),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 160),
            transitionBuilder: (child, animation) =>
                SizeTransition(sizeFactor: animation, child: child),
            child: _expanded
                ? _BoardCardDetail(key: const ValueKey('bd'), entry: entry)
                : const SizedBox(width: double.infinity, key: ValueKey('bc')),
          ),
        ],
      ),
    );
  }
}

/// 展开详情：实时任务进度 + 章节颗粒（完成/待学/锁定色点）+ 近期任务事件。
class _BoardCardDetail extends StatelessWidget {
  const _BoardCardDetail({super.key, required this.entry});

  final BoardEntry entry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final chapters = entry.detail?.chapters ?? const <ChapterStatus>[];
    final events = entry.activity.take(6).toList();

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (entry.current != null && entry.current!.progress != null) ...[
            Row(
              children: [
                Icon(boardKindIcon(entry.current!.kind),
                    size: 13, color: scheme.primary),
                const SizedBox(width: 5),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                      value: entry.current!.progress,
                      minHeight: 4,
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                Text('${(entry.current!.progress! * 100).toStringAsFixed(0)}%',
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: scheme.primary)),
              ],
            ),
            const SizedBox(height: 6),
          ],
          if (chapters.isNotEmpty) ...[
            Wrap(
              spacing: 5,
              runSpacing: 5,
              children: [
                for (final chapter in chapters)
                  Tooltip(
                    message:
                        '${chapter.index + 1}. ${chapter.title}'
                        '${chapter.finished ? ' · 已完成' : chapter.needUnlock ? ' · 待解锁' : ' · 待学习'}'
                        '${chapter.jobCount > 0 ? ' · ${chapter.jobCount}个任务点' : ''}',
                    child: Container(
                      width: 22,
                      height: 22,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: chapter.finished
                            ? scheme.tertiaryContainer
                            : chapter.needUnlock
                                ? kWarningColor.withValues(alpha: 0.22)
                                : scheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '${chapter.index + 1}',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: chapter.finished
                              ? scheme.onTertiaryContainer
                              : scheme.onSurfaceVariant,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 6),
          ],
          if (events.isNotEmpty)
            for (final event in events)
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Row(
                  children: [
                    Icon(boardKindIcon(event.kind),
                        size: 11,
                        color: event.isError
                            ? scheme.error
                            : event.isDone
                                ? scheme.tertiary
                                : scheme.outline),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Text(
                        activityTitle(event),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: scheme.onSurfaceVariant),
                      ),
                    ),
                  ],
                ),
              ),
          if (chapters.isEmpty &&
              events.isEmpty &&
              entry.current == null)
            Text('暂无章节数据 · 课程页打开详情或运行后自动补充',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: scheme.outline)),
        ],
      ),
    );
  }
}

/// 活动行标题（课程 · 动词 对象），供看板卡片与最新动态条复用。
String activityTitle(TaskActivity activity) {
  if (activity.phase == 'progress') return activity.describe();
  final verb = switch (activity.phase) {
    'start' => '开始',
    'done' => '完成',
    'error' => '异常',
    'retry' => '重试',
    'stats' => '统计',
    'scored' => '成绩',
    'finished' => '结束',
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

/// 底部最新动态条：固定高度、单行最新事件，保留“活动流”的时效感。
class _RecentStrip extends StatelessWidget {
  const _RecentStrip({required this.activity});

  final List<TaskActivity> activity;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final latest = activity.isEmpty ? null : activity.first;
    return Container(
      height: 36,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      color: scheme.surfaceContainerLow,
      child: Row(
        children: [
          Icon(Icons.bolt_outlined, size: 14, color: scheme.outline),
          const SizedBox(width: 8),
          Text('最新动态',
              style:
                  theme.textTheme.labelSmall?.copyWith(color: scheme.outline)),
          const SizedBox(width: 12),
          Expanded(
            child: latest == null
                ? Text('暂无动态',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: scheme.outline))
                : Row(
                    children: [
                      Icon(boardKindIcon(latest.kind),
                          size: 13, color: scheme.outline),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          activityTitle(latest),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall,
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

IconData boardKindIcon(String kind) => switch (kind) {
      'run' => Icons.flag_outlined,
      'chapter' => Icons.auto_stories_outlined,
      'video' => Icons.play_circle_outline,
      'audio' => Icons.graphic_eq,
      'document' => Icons.description_outlined,
      'work' => Icons.quiz_outlined,
      'read' => Icons.menu_book_outlined,
      'live' => Icons.live_tv_outlined,
      'learn' => Icons.repeat_outlined,
      _ => Icons.circle_outlined,
    };

/// 看板为空时的引导（空闲未选课 / 运行中无分课程数据两种语境）。
class _BoardEmptyGuide extends StatelessWidget {
  const _BoardEmptyGuide({required this.running});

  final bool running;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SingleChildScrollView(
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 20),
            Icon(
              running ? Icons.view_kanban_outlined : Icons.space_dashboard_outlined,
              size: 44,
              color: scheme.outline,
            ),
            const SizedBox(height: 10),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 40),
              child: Text(
                running
                    ? '等待引擎分课程数据…'
                    : '勾选课程后，这里按 进行中 / 待进行 / 已完成 展示每门课的任务与进度',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            if (!running) ...[
              const SizedBox(height: 16),
              _GuideStep(
                  order: '1',
                  text: '在「设置」填写账号与答题源，保存后写入 config.ini'),
              _GuideStep(order: '2', text: '在「课程」页刷新并勾选要学习的课程'),
              _GuideStep(order: '3', text: '回到这里点击「开始学习」，看板实时分栏展示进展'),
              _GuideStep(order: '4', text: '手动答题会弹出答题窗口，异常可到「日志」页排查'),
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
          Flexible(
              child:
                  Text(text, style: Theme.of(context).textTheme.bodySmall)),
        ],
      ),
    );
  }
}

class _BoardSkeleton extends StatelessWidget {
  const _BoardSkeleton();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var col = 0; col < 3; col++) ...[
          if (col > 0) const VerticalDivider(width: 1),
          Expanded(
            child: Column(
              children: [
                const SizedBox(height: 14),
                SkeletonBox(width: 80 + col * 20.0, height: 14, radius: 7),
                const SizedBox(height: 12),
                for (var i = 0; i < 3; i++)
                  Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    child: const SkeletonBox(height: 64, radius: 12),
                  ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}
