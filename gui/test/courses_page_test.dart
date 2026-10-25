import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/core/models.dart';
import 'package:fxxxxc/pages/courses_page.dart';
import 'package:fxxxxc/state.dart';
import 'package:shared_preferences/shared_preferences.dart';

Course _course(
  String id,
  String title, {
  String teacher = '',
  bool notOpen = false,
  String cover = '',
}) =>
    Course(
      courseId: id,
      clazzId: 'k$id',
      cpi: 'p$id',
      title: title,
      teacher: teacher,
      notOpen: notOpen,
      cover: cover,
    );

class _FakeCoursesNotifier extends CoursesNotifier {
  _FakeCoursesNotifier(this.courses);

  final List<Course> courses;

  @override
  Future<List<Course>> build() async => courses;

  @override
  Future<void> refresh() async {}
}

class _FakeStatusNotifier extends StatusNotifier {
  _FakeStatusNotifier(this.status);

  final StudyStatus status;

  @override
  StudyStatus build() => status;
}

const _detail = CourseDetail(
  courseId: 'c1',
  clazzId: 'kc1',
  chapters: [
    ChapterStatus(index: 0, title: '第一章 导论', finished: true, jobCount: 2, needUnlock: false),
    ChapterStatus(index: 1, title: '第二章 进阶', finished: false, jobCount: 1, needUnlock: true),
    ChapterStatus(index: 2, title: '第三章 实践', finished: false, jobCount: 1, needUnlock: false),
  ],
  total: 3,
  finished: 1,
  locked: 1,
  hasLocked: true,
);

ProviderContainer _container({
  required List<Course> courses,
  StudyStatus? status,
}) {
  return ProviderContainer(
    overrides: [
      coursesProvider.overrideWith(() => _FakeCoursesNotifier(courses)),
      statusProvider.overrideWith(() => _FakeStatusNotifier(
          status ?? const StudyStatus(state: 'idle'))),
      courseDetailProvider.overrideWith(
          (ref, key) => Future<CourseDetail>.value(_detail)),
    ],
  );
}

Future<void> _pumpCourses(WidgetTester tester, ProviderContainer container) async {
  SharedPreferences.setMockInitialValues({});
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 1100,
            height: 820,
            child: CoursesPage(),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 260));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('applyCourseFilter', () {
    final courses = [
      _course('1', '高职英语', teacher: '许群'),
      _course('2', '大学语文', notOpen: true),
      _course('3', '英语听力二'),
    ];

    test('query matches title/teacher/id case-insensitively', () {
      final byTitle = applyCourseFilter(courses,
          const CourseFilterState(query: '英语'), {});
      expect(byTitle.length, 2);
      final byTeacher = applyCourseFilter(courses,
          const CourseFilterState(query: '许群'), {});
      expect(byTeacher.map((c) => c.courseId), ['1']);
      final byId = applyCourseFilter(courses,
          const CourseFilterState(query: '3'), {});
      expect(byId.map((c) => c.courseId), ['3']);
    });

    test('status filters by notOpen/selected/live-running', () {
      expect(
        applyCourseFilter(courses, const CourseFilterState(status: 'notOpen'), {})
            .map((c) => c.courseId),
        ['2'],
      );
      expect(
        applyCourseFilter(
            courses,
            const CourseFilterState(status: 'selected'),
            {'1'}).map((c) => c.courseId),
        ['1'],
      );
      final live = {
        '3': const CourseProgress(
            courseId: '3', title: '英语听力二', total: 4, done: 1, failed: 0),
      };
      expect(
        applyCourseFilter(courses, const CourseFilterState(status: 'running'),
                {}, liveProgress: live)
            .map((c) => c.courseId),
        ['3'],
      );
    });

    test('sort by name', () {
      final sorted = applyCourseFilter(courses,
          const CourseFilterState(sort: 'name'), {});
      expect(
        sorted.map((c) => c.title).toList(),
        ['大学语文', '英语听力二', '高职英语']..sort(),
      );
    });
  });

  testWidgets('course cards render cover placeholder, not-open badge and live progress',
      (tester) async {
    final courses = [
      _course('1', '高职英语'),
      _course('2', '大学语文', notOpen: true),
    ];
    final status = const StudyStatus(
      state: 'running',
      coursesProgress: [
        CourseProgress(courseId: '1', title: '高职英语', total: 4, done: 1, failed: 0),
      ],
    );
    await _pumpCourses(tester, _container(courses: courses, status: status));

    expect(find.text('高职英语'), findsOneWidget);
    expect(find.text('大学语文'), findsOneWidget);
    // 「未开放」同时出现在筛选 chip 和卡片徽标里，限定卡片作用域
    expect(
      find.descendant(of: find.byType(Card), matching: find.text('未开放')),
      findsOneWidget,
    );
    // 本轮实时进度优先于章节明细
    expect(find.text('本轮 1/4 章'), findsOneWidget);
    // 封面缺失时回退首字占位
    expect(find.text('高'), findsOneWidget);
  });

  testWidgets('search box filters the grid', (tester) async {
    final courses = [
      _course('1', '高职英语'),
      _course('2', '大学语文'),
      _course('3', '英语听力二'),
    ];
    await _pumpCourses(tester, _container(courses: courses));

    await tester.enterText(find.byType(TextField), '英语');
    await tester.pump(const Duration(milliseconds: 60));

    expect(find.text('高职英语'), findsOneWidget);
    expect(find.text('英语听力二'), findsOneWidget);
    expect(find.text('大学语文'), findsNothing);
    expect(find.text('2 / 3 门'), findsOneWidget);
    // 让筛选持久化的 300ms 防抖 Timer 跑完，避免测试收尾时挂起定时器
    await tester.pump(const Duration(milliseconds: 400));
  });

  testWidgets('cover tap opens detail sheet with chapter states', (tester) async {
    final courses = [_course('1', '高职英语')];
    await _pumpCourses(tester, _container(courses: courses));

    await tester.tap(find.text('高')); // 封面占位首字
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('共 3 章'), findsOneWidget);
    expect(find.text('已完成 1'), findsOneWidget);
    expect(find.text('待解锁 1'), findsOneWidget);
    expect(find.textContaining('第一章 导论'), findsOneWidget);
    expect(find.textContaining('第二章 进阶'), findsOneWidget);
    expect(find.text('该课程章节需要按顺序学习解锁，建议从第一个未完成章节开始。'), findsOneWidget);
  });

  testWidgets('not-open filter chip narrows the grid', (tester) async {
    final courses = [
      _course('1', '高职英语'),
      _course('2', '大学语文', notOpen: true),
    ];
    await _pumpCourses(tester, _container(courses: courses));

    // 点筛选 chip（不是卡片上的未开放徽标）
    await tester.tap(find.ancestor(
      of: find.text('未开放'), matching: find.byType(ChoiceChip)).first);
    await tester.pump(const Duration(milliseconds: 60));

    expect(find.text('大学语文'), findsOneWidget);
    expect(find.text('高职英语'), findsNothing);
    await tester.pump(const Duration(milliseconds: 400));
  });
}
