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
