import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/engine_client.dart';
import 'core/models.dart';

final engineClientProvider = Provider<EngineClient>((ref) => EngineClient());

const _selectedCoursesKey = 'selected_courses';

enum ConnState { connecting, ready, error }

class ConnectionNotifier extends Notifier<ConnState> {
  StreamSubscription? _sub;
  Timer? _poll;
  Timer? _logFlush;
  final List<LogEntry> _logBuffer = [];
  Timer? _activityFlush;
  final List<TaskActivity> _activityBuffer = [];
  bool _starting = false;

  @override
  ConnState build() {
    final client = ref.read(engineClientProvider);
    ref.onDispose(() {
      _sub?.cancel();
      _poll?.cancel();
      _logFlush?.cancel();
      _activityFlush?.cancel();
      // Belt for container teardown; the window-close handler is the primary
      // kill path (dispose may not run before process teardown).
      unawaited(client.stop());
    });
    // Startup is triggered from AppShell's post-frame callback so the first
    // frame paints immediately; never block it on process/native work.
    return ConnState.connecting;
  }

  Future<void> ensureStarted() async {
    if (_starting || state == ConnState.ready) return;
    _starting = true;
    try {
      await start();
      unawaited(ref.read(selectedCoursesProvider.notifier).restore());
    } finally {
      _starting = false;
    }
  }

  Future<void> start() async {
    final client = ref.read(engineClientProvider);
    try {
      await client.start();
      _sub?.cancel();
      _sub = client.events.listen(_onEvent);
      _poll?.cancel();
      _poll = Timer.periodic(const Duration(seconds: 2), (_) => refreshStatus());
      state = ConnState.ready;
      await refreshStatus();
    } on EngineException catch (error) {
      state = ConnState.error;
      ref.read(lastErrorProvider.notifier).state = error.message;
    } catch (error) {
      state = ConnState.error;
      ref.read(lastErrorProvider.notifier).state = '$error';
    }
  }

  void _onEvent(Map<String, dynamic> event) {
    final type = '${event['type'] ?? ''}';
    final data = (event['data'] as Map?)?.cast<String, dynamic>() ?? const {};
    switch (type) {
      case 'log':
        // Batch log floods: one list rebuild per 150ms instead of per line.
        _logBuffer.add(LogEntry.fromJson(data));
        _logFlush ??= Timer(const Duration(milliseconds: 150), () {
          final batch = List<LogEntry>.of(_logBuffer);
          _logBuffer.clear();
          _logFlush = null;
          if (batch.isNotEmpty) {
            ref.read(logsProvider.notifier).addAll(batch);
          }
        });
        break;
      case 'study.task':
        _onStudyTask(data);
        break;
      case 'state.changed':
        ref.read(statusProvider.notifier).patchState(
              '${data['state'] ?? ''}',
              '${data['detail'] ?? ''}',
            );
        break;
      case 'study.progress':
        // 加载课程阶段的细粒度上下文（engine 每门课发一条），反馈到状态详情。
        if ('${data['phase'] ?? ''}' == 'loading_course') {
          final title = '${data['course_title'] ?? ''}';
          ref.read(statusProvider.notifier).patchState(
                'loading',
                title.isEmpty ? '正在加载课程' : '正在加载课程：$title',
              );
        }
        break;
      case 'config.changed':
        // CLI 或其他端改了配置：让设置页回读最新值（脏字段由设置页自行保护）。
        ref.invalidate(configProvider);
        break;
      case 'manual.question':
        ref.read(manualProvider.notifier).setBatch(data);
        break;
      case 'manual.answered':
        ref.read(manualProvider.notifier).onAnswered(
              '${data['batch_id'] ?? ''}',
              (data['index'] as num?)?.toInt() ?? -1,
            );
        break;
      case 'course.list':
        ref.read(coursesProvider.notifier).refresh();
        break;
      default:
        break;
    }
  }

  void _onStudyTask(Map<String, dynamic> data) {
    final activity = TaskActivity.fromJson(data, DateTime.now());
    final statusNotifier = ref.read(statusProvider.notifier);
    statusNotifier.applyTask(activity);

    // 视频每秒的 progress 事件不进活动流，只更新“当前任务”快照，
    // 否则活动流会被刷屏；其余事件进入流（同样合并 150ms 内的多条）。
    if (!(activity.kind == 'video' || activity.kind == 'audio') || activity.phase != 'progress') {
      _activityBuffer.add(activity);
      _activityFlush ??= Timer(const Duration(milliseconds: 150), () {
        final batch = List<TaskActivity>.of(_activityBuffer);
        _activityBuffer.clear();
        _activityFlush = null;
        if (batch.isNotEmpty) {
          ref.read(activityProvider.notifier).addAll(batch);
        }
      });
    }
  }

  Future<void> refreshStatus() async {
    if (state != ConnState.ready) return;
    try {
      final result = await ref.read(engineClientProvider).rpc('study.status');
      if (result is Map) {
        final status = StudyStatus.fromJson((result).cast<String, dynamic>());
        ref.read(statusProvider.notifier).replace(status);
        // 双向同步的引擎半边：本地没有持久化选课时，恢复引擎侧上次的选课。
        if (status.lastCourseIds.isNotEmpty) {
          ref.read(selectedCoursesProvider.notifier).seedIfEmpty(status.lastCourseIds);
        }
      }
    } on EngineException {
      // Engine is restarting; the next poll will retry.
    }
  }

  Future<void> retry() async {
    state = ConnState.connecting;
    await start();
  }
}

class LastErrorNotifier extends Notifier<String?> {
  @override
  String? build() => null;
  // ignore: use_setters_to_change_properties
  void set(String? value) => state = value;
}

final lastErrorProvider = NotifierProvider<LastErrorNotifier, String?>(
  LastErrorNotifier.new,
);

final connectionProvider =
    NotifierProvider<ConnectionNotifier, ConnState>(ConnectionNotifier.new);

class LogsNotifier extends Notifier<List<LogEntry>> {
  static const _maxLines = 800;

  @override
  List<LogEntry> build() => const [];

  void add(LogEntry entry) => addAll([entry]);

  void addAll(List<LogEntry> entries) {
    if (entries.isEmpty) return;
    final next = [...state, ...entries];
    if (next.length > _maxLines) {
      next.removeRange(0, next.length - _maxLines);
    }
    state = next;
  }

  void clear() => state = const [];
}

final logsProvider = NotifierProvider<LogsNotifier, List<LogEntry>>(LogsNotifier.new);

class ActivityNotifier extends Notifier<List<TaskActivity>> {
  static const _maxEntries = 80;

  @override
  List<TaskActivity> build() => const [];

  void addAll(List<TaskActivity> entries) {
    if (entries.isEmpty) return;
    final next = [...entries.reversed, ...state];
    if (next.length > _maxEntries) {
      next.removeRange(_maxEntries, next.length);
    }
    state = next;
  }

  void clear() => state = const [];
}

/// 倒序活动流（最新在最上），仪表盘结构化展示的数据源。
final activityProvider = NotifierProvider<ActivityNotifier, List<TaskActivity>>(ActivityNotifier.new);

class StatusNotifier extends Notifier<StudyStatus> {
  @override
  StudyStatus build() => const StudyStatus();

  // ignore: use_setters_to_change_properties
  void replace(StudyStatus status) => state = status;

  void patchState(String newState, String newDetail) {
    if (newState.isEmpty) return;
    state = state.copyWith(
      state: newState,
      detail: newDetail.isNotEmpty ? newDetail : null,
    );
  }

  /// 引擎 study.task 事件 → 状态快照（当前任务、覆盖率、成绩）。
  void applyTask(TaskActivity activity) {
    if (activity.kind == 'run') {
      if (activity.phase == 'start') {
        ref.read(activityProvider.notifier).clear();
        // 新一轮运行：计数与当前任务快照全部归零。
        state = StudyStatus(
          state: 'loading',
          detail: state.detail,
          courses: state.courses,
          tikuQueries: state.tikuQueries,
          tikuHits: state.tikuHits,
          lastCourseIds: state.lastCourseIds,
        );
      }
      return;
    }

    StudyStatus next = state.copyWith(current: activity);
    if (activity.kind == 'work' && activity.phase == 'stats' && activity.coverRate != null) {
      next = next.copyWith(coverRate: activity.coverRate);
    }
    if (activity.kind == 'work' && activity.phase == 'scored' && activity.score != null) {
      next = next.copyWith(lastScore: activity.score);
    }
    state = next;
  }
}

final statusProvider = NotifierProvider<StatusNotifier, StudyStatus>(StatusNotifier.new);

class ManualQueue {
  const ManualQueue({this.batchId = '', this.questions = const [], this.index = 0});

  final String batchId;
  final List<ManualQuestion> questions;
  final int index;

  bool get isEmpty => questions.isEmpty;
  ManualQuestion? get current => index < questions.length ? questions[index] : null;
}

class ManualNotifier extends Notifier<ManualQueue> {
  @override
  ManualQueue build() => const ManualQueue();

  void setBatch(Map<String, dynamic> data) {
    final batchId = '${data['batch_id'] ?? ''}';
    final raw = (data['questions'] as List?) ?? const [];
    final questions = <ManualQuestion>[];
    for (var index = 0; index < raw.length; index++) {
      final item = (raw[index] as Map).cast<String, dynamic>();
      questions.add(ManualQuestion(
        batchId: batchId,
        index: index,
        title: '${item['title'] ?? ''}',
        type: '${item['type'] ?? ''}',
        options: '${item['options'] ?? ''}',
      ));
    }
    state = ManualQueue(batchId: batchId, questions: questions, index: 0);
  }

  void onAnswered(String batchId, int index) {
    if (state.batchId != batchId) return;
    final next = index + 1;
    state = next >= state.questions.length
        ? const ManualQueue()
        : ManualQueue(batchId: state.batchId, questions: state.questions, index: next);
  }

  void dismiss() => state = const ManualQueue();
}

final manualProvider = NotifierProvider<ManualNotifier, ManualQueue>(ManualNotifier.new);

class CoursesNotifier extends AsyncNotifier<List<Course>> {
  bool _refreshing = false;

  static const _diskCacheKey = 'courses_cache_v2';

  @override
  Future<List<Course>> build() async {
    final connection = ref.watch(connectionProvider);
    if (connection != ConnState.ready) return const [];
    // 冷启动先回放磁盘缓存立即出内容（stale-while-revalidate），后台再刷新。
    final cached = await _readDiskCache();
    if (cached.isNotEmpty) {
      unawaited(_fetchAndStore());
      return cached;
    }
    return _fetchAndStore();
  }

  Future<List<Course>> _fetchAndStore() async {
    final client = ref.read(engineClientProvider);
    final result = await client.rpc('courses.list', {'refresh': true});
    final items = (result is Map ? result['courses'] as List? : null) ?? const [];
    final courses = items
        .map((item) => Course.fromJson((item as Map).cast<String, dynamic>()))
        .toList();
    unawaited(_writeDiskCache(courses));
    return courses;
  }

  Future<List<Course>> _readDiskCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_diskCacheKey);
      if (raw == null || raw.isEmpty) return const [];
      final decoded = jsonDecode(raw) as List? ?? const [];
      return decoded
          .whereType<Map>()
          .map((item) => Course.fromJson(item.cast<String, dynamic>()))
          .toList();
    } catch (_) {
      return const [];
    }
  }

  Future<void> _writeDiskCache(List<Course> courses) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _diskCacheKey,
        jsonEncode([for (final course in courses) course.toJson()]),
      );
    } catch (_) {
      // 缓存失败不影响功能。
    }
  }

  Future<void> refresh() async {
    if (_refreshing) return; // 防抖：进行中的刷新直接忽略
    _refreshing = true;
    // 旧数据保留显示（stale-while-revalidate），避免每次刷新闪骨架屏。
    try {
      final courses = await _fetchAndStore();
      state = AsyncData(courses);
      // 状态同步：课程列表变化后修剪已失效的选课 ID。
      if (courses.isNotEmpty) {
        ref
            .read(selectedCoursesProvider.notifier)
            .retainAll(courses.map((course) => course.courseId).toSet());
      }
    } catch (error, stack) {
      // 已有数据时保持展示，只把错误带出去；无数据才进入错误态。
      if (state is! AsyncData<List<Course>>) {
        state = AsyncError(error, stack);
      }
    } finally {
      _refreshing = false;
    }
  }
}

final coursesProvider =
    AsyncNotifierProvider<CoursesNotifier, List<Course>>(CoursesNotifier.new);

/// 并发闸门：章节详情预取最多同时 3 个请求，防止滚动时打出请求风暴。
class FetchGate {
  FetchGate(this.maxConcurrent);

  final int maxConcurrent;
  int _running = 0;
  final Queue<Completer<void>> _waiters = Queue<Completer<void>>();

  Future<void> acquire() {
    if (_running < maxConcurrent) {
      _running++;
      return Future.value();
    }
    final completer = Completer<void>();
    _waiters.add(completer);
    return completer.future;
  }

  void release() {
    if (_waiters.isNotEmpty) {
      _waiters.removeFirst().complete();
      return;
    }
    _running = (_running - 1).clamp(0, maxConcurrent);
  }
}

final _courseDetailGate = FetchGate(3);

/// 课程章节状态详情（键：`courseId|clazzId|cpi`）。
/// keepAlive 缓存 + 卡片构建时预取；详情弹窗里可 invalidate 强刷。
final courseDetailProvider =
    FutureProvider.family<CourseDetail, String>((ref, key) async {
  final parts = key.split('|');
  await _courseDetailGate.acquire();
  try {
    final result = await ref.read(engineClientProvider).rpc('course.detail', {
      'course_id': parts.isNotEmpty ? parts[0] : '',
      'clazz_id': parts.length > 1 ? parts[1] : '',
      'cpi': parts.length > 2 ? parts[2] : '',
    });
    return CourseDetail.fromJson((result as Map).cast<String, dynamic>());
  } finally {
    _courseDetailGate.release();
  }
});

/// 课程页筛选/排序状态（查询词、状态、排序），持久化到本地。
class CourseFilterState {
  const CourseFilterState({
    this.query = '',
    this.status = 'all',
    this.sort = 'default',
  });

  final String query;
  final String status; // all | running | notOpen | selected
  final String sort; // default | name

  bool get isDefault =>
      query.isEmpty && status == 'all' && sort == 'default';

  CourseFilterState copyWith({
    String? query,
    String? status,
    String? sort,
  }) =>
      CourseFilterState(
        query: query ?? this.query,
        status: status ?? this.status,
        sort: sort ?? this.sort,
      );
}

class CoursesFilterNotifier extends Notifier<CourseFilterState> {
  static const _persistKey = 'courses_filter_v1';
  Timer? _persistTimer;

  @override
  CourseFilterState build() {
    // 恢复持久化的筛选状态（异步回填，不阻塞首帧）。
    unawaited(_restore());
    ref.onDispose(() => _persistTimer?.cancel());
    return const CourseFilterState();
  }

  Future<void> _restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_persistKey);
      if (raw == null) return;
      final decoded = jsonDecode(raw) as Map? ?? const {};
      state = CourseFilterState(
        query: '${decoded['query'] ?? ''}',
        status: '${decoded['status'] ?? 'all'}',
        sort: '${decoded['sort'] ?? 'default'}',
      );
    } catch (_) {
      // 恢复失败保持默认。
    }
  }

  void _update(CourseFilterState next) {
    state = next;
    // 持久化做 300ms 防抖，快速敲字不写盘。
    _persistTimer?.cancel();
    _persistTimer = Timer(const Duration(milliseconds: 300), () {
      unawaited(_persist());
    });
  }

  Future<void> _persist() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_persistKey, jsonEncode({
        'query': state.query,
        'status': state.status,
        'sort': state.sort,
      }));
    } catch (_) {}
  }

  // ignore: use_setters_to_change_properties
  void setQuery(String query) => _update(state.copyWith(query: query));

  void setStatus(String status) => _update(state.copyWith(status: status));

  void setSort(String sort) => _update(state.copyWith(sort: sort));

  void reset() => _update(const CourseFilterState());
}

final coursesFilterProvider =
    NotifierProvider<CoursesFilterNotifier, CourseFilterState>(
        CoursesFilterNotifier.new);

/// 把筛选/排序应用到课程列表（纯函数，供页面与测试共用）。
List<Course> applyCourseFilter(
  List<Course> courses,
  CourseFilterState filter,
  Set<String> selectedIds, {
  Map<String, CourseProgress> liveProgress = const {},
}) {
  var result = courses;
  final query = filter.query.trim().toLowerCase();
  if (query.isNotEmpty) {
    bool matches(Course course) =>
        course.title.toLowerCase().contains(query) ||
        course.teacher.toLowerCase().contains(query) ||
        course.courseId.contains(query);
    result = result.where(matches).toList();
  }
  switch (filter.status) {
    case 'running':
      result = result
          .where((course) =>
              liveProgress[course.courseId]?.isRunning ?? false)
          .toList();
      break;
    case 'notOpen':
      result = result.where((course) => course.notOpen).toList();
      break;
    case 'selected':
      result = result
          .where((course) => selectedIds.contains(course.courseId))
          .toList();
      break;
  }
  if (filter.sort == 'name') {
    final sorted = [...result]..sort((a, b) => a.title.compareTo(b.title));
    result = sorted;
  }
  return result;
}

class SelectedCoursesNotifier extends Notifier<Set<String>> {
  @override
  Set<String> build() => {};

  /// Restore persisted selection (GUI ↔ 引擎状态双向同步的本地半边)。
  Future<void> restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getStringList(_selectedCoursesKey) ?? const [];
      if (saved.isNotEmpty && state.isEmpty) {
        state = saved.toSet();
      }
    } catch (_) {
      // Persistence is best-effort; selection still works in-memory.
    }
  }

  /// 引擎半边：本地无选课时恢复引擎侧上次运行的选课集合。
  void seedIfEmpty(List<String> courseIds) {
    if (state.isNotEmpty || courseIds.isEmpty) return;
    state = courseIds.toSet();
  }

  Future<void> _persist() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_selectedCoursesKey, state.toList());
    } catch (_) {}
  }

  void toggle(String courseId) {
    final next = {...state};
    if (!next.remove(courseId)) next.add(courseId);
    state = next;
    unawaited(_persist());
  }

  void selectAll(List<Course> courses) {
    final all = courses.map((course) => course.courseId).toSet();
    state = state.length == all.length ? <String>{} : all;
    unawaited(_persist());
  }

  void clear() {
    state = {};
    unawaited(_persist());
  }

  void retainAll(Set<String> ids) {
    final next = state.intersection(ids);
    if (next.length != state.length) {
      state = next;
      unawaited(_persist());
    }
  }
}

final selectedCoursesProvider =
    NotifierProvider<SelectedCoursesNotifier, Set<String>>(SelectedCoursesNotifier.new);

class ConfigNotifier extends AsyncNotifier<Map<String, dynamic>> {
  @override
  Future<Map<String, dynamic>> build() async {
    final connection = ref.watch(connectionProvider);
    if (connection != ConnState.ready) return const {};
    final result = await ref.read(engineClientProvider).rpc('config.get');
    if (result is Map && result['config'] is Map) {
      return (result['config'] as Map).cast<String, dynamic>();
    }
    return const {};
  }

  Future<void> save(Map<String, Map<String, String>> patch) async {
    await ref.read(engineClientProvider).rpc('config.set', {'config': patch});
    ref.invalidateSelf();
  }
}

final configProvider =
    AsyncNotifierProvider<ConfigNotifier, Map<String, dynamic>>(ConfigNotifier.new);

class ThemeModeNotifier extends Notifier<ThemeMode> {
  @override
  ThemeMode build() => ThemeMode.system;

  void set(ThemeMode mode) => state = mode;
}

final themeModeProvider = NotifierProvider<ThemeModeNotifier, ThemeMode>(ThemeModeNotifier.new);
