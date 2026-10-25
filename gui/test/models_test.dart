import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/core/models.dart';

void main() {
  group('StudyStatus', () {
    test('parses engine payload', () {
      final status = StudyStatus.fromJson({
        'state': 'running',
        'detail': '共 12 个章节',
        'total': 12,
        'done': 3,
        'failed': 1,
        'courses': 2,
      });
      expect(status.state, 'running');
      expect(status.total, 12);
      expect(status.done, 3);
      expect(status.failed, 1);
      expect(status.progress, closeTo(0.25, 0.001));
    });

    test('progress is zero without tasks', () {
      expect(const StudyStatus().progress, 0);
    });

    test('parses current snapshot, elapsed and last course ids', () {
      final status = StudyStatus.fromJson({
        'state': 'running',
        'elapsed': 95,
        'last_course_ids': ['123', '456'],
        'current': {'kind': 'video', 'phase': 'progress', 'name': '1.1 导论', 'progress': 0.42},
        'tiku_stats': {
          '甲库(TikuYanxi)': {'queries': 10, 'hits': 7},
          '乙库(AI)': {'queries': 3, 'hits': 3},
        },
      });
      expect(status.elapsed, 95);
      expect(status.lastCourseIds, ['123', '456']);
      expect(status.current, isNotNull);
      expect(status.current!.kind, 'video');
      expect(status.current!.progress, closeTo(0.42, 0.001));
      expect(status.tikuQueries, 13);
      expect(status.tikuHits, 10);
      expect(status.hitRate, closeTo(10 / 13, 0.001));
    });

    test('hitRate is null without queries', () {
      expect(const StudyStatus().hitRate, isNull);
    });

    test('copyWith keeps unspecified fields', () {
      const base = StudyStatus(state: 'running', detail: 'd', total: 10, done: 2, failed: 1);
      final next = base.copyWith(state: 'paused');
      expect(next.state, 'paused');
      expect(next.detail, 'd');
      expect(next.total, 10);
      expect(next.done, 2);
      expect(next.failed, 1);
    });
  });

  group('TaskActivity', () {
    test('parses study.task payload', () {
      final activity = TaskActivity.fromJson({
        'kind': 'chapter',
        'phase': 'done',
        'course': '课程A',
        'chapter': '第一章',
        'result': 'success',
      }, DateTime(2026, 1, 1));
      expect(activity.kind, 'chapter');
      expect(activity.isDone, isTrue);
      expect(activity.isError, isFalse);
    });

    test('kindLabel maps known kinds', () {
      expect(TaskActivity.kindLabel('video'), '视频');
      expect(TaskActivity.kindLabel('work'), '章节检测');
      expect(TaskActivity.kindLabel('mystery'), '任务');
    });

    test('describe formats stats and retry', () {
      final stats = TaskActivity.fromJson({
        'kind': 'work',
        'phase': 'stats',
        'name': 'work-1',
        'cover_rate': 83.3,
      });
      expect(stats.describe(), contains('83%'));
      final retry = TaskActivity.fromJson({
        'kind': 'chapter',
        'phase': 'retry',
        'course': '课程A',
        'chapter': '第二章',
        'tries': 2,
      });
      expect(retry.describe(), contains('第 2 次'));
      expect(retry.isRetry, isTrue);
    });
  });

  group('Course', () {
    test('parses engine payload', () {
      final course = Course.fromJson({
        'courseId': 123,
        'clazzId': '456',
        'title': '测试课程',
        'teacher': '老师',
        'cpi': '7',
      });
      expect(course.courseId, '123');
      expect(course.clazzId, '456');
      expect(course.title, '测试课程');
    });
  });

  group('ManualQuestion', () {
    test('splits options and maps type labels', () {
      const question = ManualQuestion(
        batchId: 'b',
        index: 0,
        title: '题目',
        type: 'judgement',
        options: 'A. 正确\nB. 错误',
      );
      expect(question.optionList, ['A. 正确', 'B. 错误']);
      expect(question.typeLabel, '判断题');
    });

    test('unknown type falls back', () {
      const question = ManualQuestion(
        batchId: 'b',
        index: 1,
        title: '题目',
        type: 'other',
        options: '',
      );
      expect(question.typeLabel, '题目');
      expect(question.optionList, isEmpty);
    });
  });
}
