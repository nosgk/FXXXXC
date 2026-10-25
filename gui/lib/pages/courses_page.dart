import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/skeleton.dart';

/// 课程库：响应式封面卡片网格 + 每门课程的详细状态。
///
/// 状态来源分三层：平台侧未开放标记（列表自带）、章节状态明细（course.detail，
/// 卡片构建时按需预取 + 并发限流）、本轮运行的实时进度（study.status 轮询）。
class CoursesPage extends ConsumerWidget {
  const CoursesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final coursesAsync = ref.watch(coursesProvider);
    final liveProgress =
        ref.watch(statusProvider.select((status) => status.coursesProgress));

    final body = coursesAsync.when(
      loading: () => const _SkeletonGrid(),
      error: (error, stack) => _ErrorView(
        message: '$error',
        onRetry: () => ref.read(coursesProvider.notifier).refresh(),
      ),
      data: (courses) {
        if (courses.isEmpty) {
          return _EmptyView(
              onRefresh: () => ref.read(coursesProvider.notifier).refresh());
        }
        return _CourseLibrary(
          courses: courses,
          liveProgress: {
            for (final item in liveProgress) item.courseId: item,
          },
        );
      },
    );

    // 状态切换（骨架→内容→错误）统一 240ms 淡入，避免硬切。
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 240),
      child: KeyedSubtree(
        key: ValueKey(coursesAsync.runtimeType),
        child: body,
      ),
    );
  }
}

// ---------------------------------------------------------------- 课程库主体

class _CourseLibrary extends ConsumerWidget {
  const _CourseLibrary({required this.courses, required this.liveProgress});

  final List<Course> courses;
  final Map<String, CourseProgress> liveProgress;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(coursesFilterProvider);
    final selectedIds = ref.watch(selectedCoursesProvider);
    final filtered = applyCourseFilter(courses, filter, selectedIds,
        liveProgress: liveProgress);

    return Column(
      children: [
        _CoursesHeader(
          total: courses.length,
          shownCount: filtered.length,
          liveCount:
              liveProgress.values.where((item) => item.isRunning).length,
        ),
        Expanded(
          child: filtered.isEmpty
              ? _FilteredEmptyView(
                  onReset: () => ref.read(coursesFilterProvider.notifier).reset())
              : GridView.builder(
                  padding: const EdgeInsets.all(24),
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                    maxCrossAxisExtent: 340,
                    mainAxisExtent: 252,
                    crossAxisSpacing: 12,
                    mainAxisSpacing: 12,
                  ),
                  // GridView.builder 自带虚拟化：只构建可见 + 缓存区的卡片，
                  // 卡片在构建时才预取章节详情（缓存区即预取窗口）。
                  itemCount: filtered.length,
                  findChildIndexCallback: (key) {
                    // 筛选/排序变化后复用已有卡片元素，避免封面图重载闪烁。
                    final id = (key as ValueKey<String>).value;
                    final index =
                        filtered.indexWhere((item) => item.courseId == id);
                    return index < 0 ? null : index;
                  },
                  itemBuilder: (context, index) {
                    final course = filtered[index];
                    return _CourseCard(
                      key: ValueKey(course.courseId),
                      course: course,
                      live: liveProgress[course.courseId],
                    );
                  },
                ),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------ 顶部工具区

class _CoursesHeader extends ConsumerStatefulWidget {
  const _CoursesHeader({
    required this.total,
    required this.shownCount,
    required this.liveCount,
  });

  final int total;
  final int shownCount;
  final int liveCount;

  @override
  ConsumerState<_CoursesHeader> createState() => _CoursesHeaderState();
}

class _CoursesHeaderState extends ConsumerState<_CoursesHeader> {
  late final TextEditingController _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filter = ref.watch(coursesFilterProvider);
    final notifier = ref.read(coursesFilterProvider.notifier);
    final theme = Theme.of(context);
    final selectedCount = ref.watch(
      selectedCoursesProvider.select((set) => set.length),
    );
    final coursesCount = ref.watch(
      coursesProvider.select(
        (async) => async.value?.length ?? 0,
      ),
    );

    // 只在外部变更（清空/恢复持久化）时同步控制器，绝不打断输入焦点。
    if (_search.text != filter.query) {
      _search.value = TextEditingValue(
        text: filter.query,
        selection: TextSelection.collapsed(offset: filter.query.length),
      );
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
      child: Column(
        children: [
          Row(
            children: [
              Text('课程', style: theme.textTheme.titleMedium),
              const SizedBox(width: 8),
              Text(
                widget.shownCount == widget.total
                    ? '${widget.total} 门'
                    : '${widget.shownCount} / ${widget.total} 门',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
              const Spacer(),
              SizedBox(
                width: 260,
                child: TextField(
                  controller: _search,
                  onChanged: notifier.setQuery,
                  decoration: InputDecoration(
                    isDense: true,
                    prefixIcon: const Icon(Icons.search, size: 20),
                    suffixIcon: filter.query.isEmpty
                        ? null
                        : IconButton(
                            visualDensity: VisualDensity.compact,
                            icon: const Icon(Icons.close, size: 18),
                            onPressed: () => notifier.setQuery(''),
                          ),
                    hintText: '搜索课程名 / 教师 / ID',
                    border: const OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              PopupMenuButton<String>(
                tooltip: '排序方式',
                icon: const Icon(Icons.sort),
                initialValue: filter.sort,
                onSelected: notifier.setSort,
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'default', child: Text('平台默认顺序')),
                  PopupMenuItem(value: 'name', child: Text('按课程名')),
                ],
              ),
              const SizedBox(width: 4),
              TextButton.icon(
                onPressed: coursesCount == 0
                    ? null
                    : () => ref.read(selectedCoursesProvider.notifier).selectAll(
                          ref.read(coursesProvider).value ?? const [],
                        ),
                icon: const Icon(Icons.select_all, size: 18),
                label: Text(selectedCount == coursesCount && coursesCount > 0
                    ? '取消全选'
                    : '全选'),
              ),
              const SizedBox(width: 4),
              FilledButton.tonalIcon(
                onPressed: () {
                  // 刷新课程列表时一并让章节详情回源。
                  ref.invalidate(courseDetailProvider);
                  ref.read(coursesProvider.notifier).refresh();
                },
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('刷新'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            children: [
              _FilterChip(
                label: '全部',
                value: 'all',
                groupValue: filter.status,
                onSelected: notifier.setStatus,
              ),
              _FilterChip(
                label: '学习中',
                value: 'running',
                groupValue: filter.status,
                onSelected: notifier.setStatus,
                leading: widget.liveCount > 0
                    ? Container(
                        width: 7,
                        height: 7,
                        decoration: const BoxDecoration(
                          color: kSuccessColor,
                          shape: BoxShape.circle,
                        ),
                      )
                    : null,
              ),
              _FilterChip(
                label: '未开放',
                value: 'notOpen',
                groupValue: filter.status,
                onSelected: notifier.setStatus,
              ),
              _FilterChip(
                label: selectedCount > 0 ? '已选 ($selectedCount)' : '已选',
                value: 'selected',
                groupValue: filter.status,
                onSelected: notifier.setStatus,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.value,
    required this.groupValue,
    required this.onSelected,
    this.leading,
  });

  final String label;
  final String value;
  final String groupValue;
  final ValueChanged<String> onSelected;
  final Widget? leading;

  @override
  Widget build(BuildContext context) {
    return ChoiceChip(
      label: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (leading != null) ...[leading!, const SizedBox(width: 6)],
          Text(label),
        ],
      ),
      selected: groupValue == value,
      onSelected: (selected) {
        if (selected) onSelected(value);
      },
    );
  }
}

// -------------------------------------------------------------------- 课程卡

class _CourseCard extends ConsumerWidget {
  const _CourseCard({super.key, required this.course, this.live});

  final Course course;
  final CourseProgress? live;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(
      selectedCoursesProvider.select((set) => set.contains(course.courseId)),
    );
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Card(
      clipBehavior: Clip.antiAlias,
      margin: EdgeInsets.zero,
      color: selected ? scheme.secondaryContainer : null,
      child: InkWell(
        onTap: () =>
            ref.read(selectedCoursesProvider.notifier).toggle(course.courseId),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _CardCover(
              course: course,
              selected: selected,
              onOpenDetail: () => _openDetailSheet(context, ref, course),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      course.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w600, height: 1.25),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      course.teacher.isEmpty
                          ? 'ID ${course.courseId}'
                          : '${course.teacher} · ID ${course.courseId}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: scheme.outline),
                    ),
                    const Spacer(),
                    _CardProgress(course: course, live: live),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CardCover extends StatelessWidget {
  const _CardCover({
    required this.course,
    required this.selected,
    required this.onOpenDetail,
  });

  final Course course;
  final bool selected;
  final VoidCallback onOpenDetail;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      height: 108,
      width: double.infinity,
      child: Stack(
        fit: StackFit.expand,
        children: [
          InkWell(
            onTap: onOpenDetail,
            child: course.cover.isEmpty
                ? _CoverPlaceholder(title: course.title)
                : Image.network(
                    course.cover,
                    cacheWidth: 480, // 按显示尺寸解码，避免整图占内存
                    fit: BoxFit.cover,
                    // 封面就绪后 300ms 淡入；加载中/失败均回退占位。
                    frameBuilder: (context, child, frame, wasLoaded) {
                      if (wasLoaded) return child;
                      return AnimatedOpacity(
                        opacity: frame == null ? 0 : 1,
                        duration: const Duration(milliseconds: 300),
                        child: child,
                      );
                    },
                    errorBuilder: (_, _, _) => _CoverPlaceholder(title: course.title),
                  ),
          ),
          Positioned(
            top: 8,
            left: 8,
            child: _StatusBadge(course: course),
          ),
          Positioned(
            top: 6,
            right: 6,
            child: AnimatedScale(
              scale: selected ? 1.0 : 0.86,
              duration: const Duration(milliseconds: 160),
              child: AnimatedOpacity(
                opacity: selected ? 1 : 0.55,
                duration: const Duration(milliseconds: 160),
                child: Container(
                  decoration: BoxDecoration(
                    color: scheme.surface.withValues(alpha: 0.9),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    selected
                        ? Icons.check_circle
                        : Icons.radio_button_unchecked,
                    size: 22,
                    color: selected ? scheme.primary : scheme.outline,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 无封面/加载失败时的占位：用课程名首字 + 主题色渐变。
class _CoverPlaceholder extends StatelessWidget {
  const _CoverPlaceholder({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final char = title.trim().isEmpty ? '课' : title.trim().characters.first;
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            scheme.primaryContainer.withValues(alpha: 0.9),
            scheme.secondaryContainer.withValues(alpha: 0.9),
          ],
        ),
      ),
      child: Center(
        child: Text(
          char,
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                color: scheme.onPrimaryContainer,
                fontWeight: FontWeight.w700,
              ),
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.course});

  final Course course;

  @override
  Widget build(BuildContext context) {
    final (label, color, icon) = course.notOpen
        ? ('未开放', Colors.grey.shade700, Icons.lock_outline)
        : ('', kSuccessColor, Icons.play_arrow);
    if (label.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: Colors.white),
          const SizedBox(width: 4),
          Text(label,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11,
                  fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

/// 卡片底部进度区：本轮实时进度 > 章节明细 > 骨架占位。
class _CardProgress extends ConsumerWidget {
  const _CardProgress({required this.course, required this.live});

  final Course course;
  final CourseProgress? live;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    // 本轮运行有该课程的实时进度时优先展示。
    if (live != null && live!.total > 0) {
      return _ProgressRow(
        label: '本轮 ${live!.done}/${live!.total} 章',
        value: live!.progress,
        color: live!.failed > 0 ? kWarningColor : kSuccessColor,
        trailing: live!.failed > 0 ? '失败 ${live!.failed}' : null,
      );
    }

    final detailAsync = ref.watch(courseDetailProvider(course.detailKey));
    final detail = detailAsync.value;
    if (detail != null && detail.total > 0) {
      final done = detail.finished == detail.total;
      return _ProgressRow(
        label: done
            ? '全部 ${detail.total} 章已完成'
            : '${detail.finished}/${detail.total} 章完成',
        value: detail.progress ?? 0.0,
        color: done ? kSuccessColor : scheme.primary,
        trailing: detail.locked > 0 ? '锁定 ${detail.locked}' : null,
      );
    }

    // 明细未就绪：细骨架条占位（失败也保持安静占位，详情弹窗里给重试）。
    return Row(
      children: [
        const Expanded(child: SkeletonBox(height: 4, radius: 2)),
        const SizedBox(width: 8),
        Icon(Icons.info_outline, size: 14, color: scheme.outline),
      ],
    );
  }
}

class _ProgressRow extends StatelessWidget {
  const _ProgressRow({
    required this.label,
    required this.value,
    required this.color,
    this.trailing,
  });

  final String label;
  final double value;
  final Color color;
  final String? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
            ),
            if (trailing != null)
              Text(
                trailing!,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: kWarningColor),
              ),
          ],
        ),
        const SizedBox(height: 5),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: value.clamp(0.0, 1.0)),
            duration: const Duration(milliseconds: 400),
            curve: Curves.easeOutCubic,
            builder: (context, animated, _) => LinearProgressIndicator(
              value: animated,
              minHeight: 5,
              color: color,
              backgroundColor:
                  theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.7),
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------- 详情弹窗

void _openDetailSheet(BuildContext context, WidgetRef ref, Course course) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (sheetContext) => FractionallySizedBox(
      heightFactor: 0.86,
      child: _CourseDetailSheet(course: course),
    ),
  );
}

class _CourseDetailSheet extends ConsumerWidget {
  const _CourseDetailSheet({required this.course});

  final Course course;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detailAsync = ref.watch(courseDetailProvider(course.detailKey));
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Container(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(course.title,
                        style: theme.textTheme.titleMedium,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 2),
                    Text(
                      '课程ID ${course.courseId} · 班级 ${course.clazzId}'
                      '${course.teacher.isEmpty ? '' : ' · ${course.teacher}'}',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: scheme.outline),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: '刷新章节状态',
                onPressed: () =>
                    ref.invalidate(courseDetailProvider(course.detailKey)),
                icon: const Icon(Icons.refresh),
              ),
              IconButton(
                tooltip: '关闭',
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
          const SizedBox(height: 8),
          detailAsync.when(
            loading: () => const Expanded(
              child: SkeletonList(itemCount: 8),
            ),
            error: (error, _) => Expanded(
              child: _DetailError(
                message: '$error',
                onRetry: () => ref.invalidate(courseDetailProvider(course.detailKey)),
              ),
            ),
            data: (detail) {
              final percent =
                  detail.total == 0 ? 0.0 : (detail.finished / detail.total);
              return Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        _SummaryChip(
                          icon: Icons.auto_stories_outlined,
                          label: '共 ${detail.total} 章',
                        ),
                        _SummaryChip(
                          icon: Icons.check_circle_outline,
                          label: '已完成 ${detail.finished}',
                          color: kSuccessColor,
                        ),
                        _SummaryChip(
                          icon: Icons.radio_button_unchecked,
                          label: '待学习 ${detail.total - detail.finished - detail.locked}',
                        ),
                        if (detail.locked > 0)
                          _SummaryChip(
                            icon: Icons.lock_outline,
                            label: '待解锁 ${detail.locked}',
                            color: kWarningColor,
                          ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: TweenAnimationBuilder<double>(
                        tween: Tween(end: percent.clamp(0.0, 1.0)),
                        duration: const Duration(milliseconds: 400),
                        curve: Curves.easeOutCubic,
                        builder: (context, value, _) => LinearProgressIndicator(
                          value: value,
                          minHeight: 6,
                          backgroundColor:
                              scheme.surfaceContainerHighest.withValues(alpha: 0.7),
                        ),
                      ),
                    ),
                    if (detail.hasLocked) ...[
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Icon(Icons.info_outline,
                              size: 14, color: kWarningColor),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '该课程章节需要按顺序学习解锁，建议从第一个未完成章节开始。',
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: kWarningColor),
                            ),
                          ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 8),
                    Expanded(
                      child: detail.chapters.isEmpty
                          ? Center(
                              child: Text('没有可显示的章节',
                                  style: theme.textTheme.bodySmall))
                          : ListView.builder(
                              padding: const EdgeInsets.only(top: 4),
                              itemCount: detail.chapters.length,
                              itemExtent: 48,
                              addAutomaticKeepAlives: false,
                              itemBuilder: (context, index) {
                                final chapter = detail.chapters[index];
                                return _ChapterRow(chapter: chapter);
                              },
                            ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _SummaryChip extends StatelessWidget {
  const _SummaryChip({
    required this.icon,
    required this.label,
    this.color,
  });

  final IconData icon;
  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final tone = color ?? scheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHigh,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: tone),
          const SizedBox(width: 6),
          Text(label,
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: tone, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _ChapterRow extends StatelessWidget {
  const _ChapterRow({required this.chapter});

  final ChapterStatus chapter;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final (icon, color) = chapter.finished
        ? (Icons.check_circle, kSuccessColor)
        : chapter.needUnlock
            ? (Icons.lock_outline, kWarningColor)
            : (Icons.radio_button_unchecked, scheme.outline);

    return Row(
      children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            '${chapter.index + 1}. ${chapter.title}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: chapter.finished ? scheme.onSurfaceVariant : null,
            ),
          ),
        ),
        if (chapter.jobCount > 0)
          Text(
            '${chapter.jobCount} 个任务点',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: scheme.outline),
          ),
      ],
    );
  }
}

class _DetailError extends StatelessWidget {
  const _DetailError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.wifi_off_outlined,
              size: 36, color: theme.colorScheme.outline),
          const SizedBox(height: 10),
          Text('章节状态读取失败', style: theme.textTheme.titleSmall),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              message,
              textAlign: TextAlign.center,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.tonalIcon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('重试'),
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------------ 空/错/骨架

class _SkeletonGrid extends StatelessWidget {
  const _SkeletonGrid();

  @override
  Widget build(BuildContext context) {
    return GridView.builder(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.all(24),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 340,
        mainAxisExtent: 252,
        crossAxisSpacing: 12,
        mainAxisSpacing: 12,
      ),
      itemCount: 8,
      itemBuilder: (context, index) => Card(
        clipBehavior: Clip.antiAlias,
        margin: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SkeletonBox(height: 108, radius: 0),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SkeletonBox(width: 160 + (index % 3) * 40, height: 14),
                  const SizedBox(height: 8),
                  const SkeletonBox(width: 120, height: 10),
                  const SizedBox(height: 20),
                  const SkeletonBox(height: 4, radius: 2),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.school_outlined,
              size: 48, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 12),
          const Text('还没有读取到课程'),
          const SizedBox(height: 4),
          Text('确认账号已在「设置」配置后刷新一次',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: Theme.of(context).colorScheme.outline)),
          const SizedBox(height: 12),
          FilledButton.icon(
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh),
              label: const Text('刷新课程')),
        ],
      ),
    );
  }
}

class _FilteredEmptyView extends StatelessWidget {
  const _FilteredEmptyView({required this.onReset});

  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.filter_alt_off_outlined,
              size: 44, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 12),
          const Text('没有符合筛选条件的课程'),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onReset,
            icon: const Icon(Icons.filter_alt_off, size: 18),
            label: const Text('清除筛选'),
          ),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline,
                size: 40, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 12),
            Text('读取课程失败', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(message,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('重试')),
          ],
        ),
      ),
    );
  }
}
