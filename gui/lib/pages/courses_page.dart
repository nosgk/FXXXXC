import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models.dart';
import '../state.dart';

class CoursesPage extends ConsumerWidget {
  const CoursesPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final coursesAsync = ref.watch(coursesProvider);
    final selected = ref.watch(selectedCoursesProvider);

    return coursesAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, stack) => _ErrorView(
        message: '$error',
        onRetry: () => ref.read(coursesProvider.notifier).refresh(),
      ),
      data: (courses) => Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
            child: Row(
              children: [
                Text('${courses.length} 门课程', style: Theme.of(context).textTheme.titleMedium),
                const Spacer(),
                TextButton.icon(
                  onPressed: () => ref.read(selectedCoursesProvider.notifier).selectAll(courses),
                  icon: const Icon(Icons.select_all),
                  label: Text(selected.length == courses.length && courses.isNotEmpty ? '取消全选' : '全选'),
                ),
                const SizedBox(width: 8),
                FilledButton.tonalIcon(
                  onPressed: () => ref.read(coursesProvider.notifier).refresh(),
                  icon: const Icon(Icons.refresh),
                  label: const Text('刷新'),
                ),
              ],
            ),
          ),
          Expanded(
            child: courses.isEmpty
                ? _EmptyView(onRefresh: () => ref.read(coursesProvider.notifier).refresh())
                : ListView.separated(
                    padding: const EdgeInsets.all(24),
                    itemCount: courses.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 8),
                    itemBuilder: (context, index) => _CourseCard(
                      course: courses[index],
                      selected: selected.contains(courses[index].courseId),
                      onToggle: () => ref
                          .read(selectedCoursesProvider.notifier)
                          .toggle(courses[index].courseId),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _CourseCard extends StatelessWidget {
  const _CourseCard({
    required this.course,
    required this.selected,
    required this.onToggle,
  });

  final Course course;
  final bool selected;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      color: selected ? scheme.secondaryContainer : null,
      child: ListTile(
        onTap: onToggle,
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        leading: Checkbox(value: selected, onChanged: (_) => onToggle()),
        title: Text(course.title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text('课程ID ${course.courseId} · 班级 ${course.clazzId} · ${course.teacher}'),
        trailing: selected
            ? Icon(Icons.check_circle, color: scheme.primary)
            : Icon(Icons.radio_button_unchecked, color: scheme.outline),
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
          Icon(Icons.school_outlined, size: 48, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 12),
          const Text('还没有课程，先刷新一次'),
          const SizedBox(height: 12),
          FilledButton.icon(onPressed: onRefresh, icon: const Icon(Icons.refresh), label: const Text('刷新课程')),
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
            Text('读取课程失败', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(message, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            FilledButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: const Text('重试')),
          ],
        ),
      ),
    );
  }
}
