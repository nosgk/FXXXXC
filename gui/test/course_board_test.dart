import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/core/models.dart';
import 'package:fxxxxc/widgets/course_board.dart';

void main() {
  final now = DateTime(2026, 1, 1, 12);

  TaskActivity act(String courseId, String phase, String name, {DateTime? at}) =>
      TaskActivity(
          kind: 'video',
          phase: phase,
          name: name,
          course: '课程',
          courseId: courseId,
          atTs: at ?? now);

  test('live run: completed→done, current→active, stale→pending', () {
    final status = StudyStatus(
      state: 'running',
      current: act('b', 'progress', '2.1.mp4', at: now),
      coursesProgress: const [
        CourseProgress(courseId: 'a', title: '课程A', total: 4, done: 4, failed: 0),
        CourseProgress(courseId: 'b', title: '课程B', total: 4, done: 1, failed: 0),
        CourseProgress(courseId: 'c', title: '课程C', total: 4, done: 0, failed: 0),
      ],
    );
    // c 有一条很久以前的事件（非近期），不应进入“进行中”
    final activity = [
      act('c', 'done', '旧任务', at: now.subtract(const Duration(minutes: 10))),
    ];

    final entries = buildBoardEntries(
      status, activity, const [], const {}, const {},
      now: now,
    );

    final byId = {for (final entry in entries) entry.courseId: entry};
    expect(byId['a']!.column, BoardColumnKind.done);
    expect(byId['b']!.column, BoardColumnKind.active);
    // b 是当前任务 → 卡片携带引擎当前任务快照
    expect(byId['b']!.current?.name, '2.1.mp4');
    expect(byId['c']!.column, BoardColumnKind.pending);
  });

  test('live run: recent activity within 45s also counts as active', () {
    final status = const StudyStatus(
      state: 'running',
      coursesProgress: [
        CourseProgress(courseId: 'x', title: '课程X', total: 2, done: 1, failed: 1),
      ],
    );
    final activity = [act('x', 'error', '任务失败', at: now)];
    final entries = buildBoardEntries(status, activity, const [], const {}, const {}, now: now);
    expect(entries.single.column, BoardColumnKind.active);
    expect(entries.single.failed, 1);
  });

  test('idle: selected courses split by chapter detail', () {
    final courses = [
      const Course(courseId: 'p1', clazzId: 'k1', cpi: 'c1', title: '已完成课'),
      const Course(courseId: 'p2', clazzId: 'k2', cpi: 'c2', title: '未完成课'),
      const Course(courseId: 'p3', clazzId: 'k3', cpi: 'c3', title: '未选课'),
    ];
    const detailDone = CourseDetail(
        courseId: 'p1', clazzId: 'k1', chapters: [], total: 3, finished: 3, locked: 0, hasLocked: false);
    const detailPart = CourseDetail(
        courseId: 'p2', clazzId: 'k2', chapters: [], total: 3, finished: 1, locked: 0, hasLocked: false);

    final entries = buildBoardEntries(
      const StudyStatus(state: 'idle'),
      const [],
      courses,
      {
        'p1|k1|c1': AsyncValue<CourseDetail>.data(detailDone),
        'p2|k2|c2': AsyncValue<CourseDetail>.data(detailPart),
      },
      const {'p1', 'p2'},
      now: now,
    );

    expect(entries.length, 2); // 未选中的 p3 不出现
    final byTitle = {for (final entry in entries) entry.title: entry};
    expect(byTitle['已完成课']!.column, BoardColumnKind.done);
    expect(byTitle['已完成课']!.total, 3);
    expect(byTitle['未完成课']!.column, BoardColumnKind.pending);
  });

  test('empty state when nothing selected and no run', () {
    final entries = buildBoardEntries(
        const StudyStatus(state: 'idle'), const [], const [], const {}, const {});
    expect(entries, isEmpty);
  });
}
