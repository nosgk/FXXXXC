import 'dart:async';

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
  bool _starting = false;

  @override
  ConnState build() {
    final client = ref.read(engineClientProvider);
    ref.onDispose(() {
      _sub?.cancel();
      _poll?.cancel();
      _logFlush?.cancel();
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
      case 'state.changed':
        ref.read(statusProvider.notifier).patchState(
              '${data['state'] ?? ''}',
              '${data['detail'] ?? ''}',
            );
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

  Future<void> refreshStatus() async {
    if (state != ConnState.ready) return;
    try {
      final result = await ref.read(engineClientProvider).rpc('study.status');
      if (result is Map) {
        ref.read(statusProvider.notifier).replace(
              StudyStatus.fromJson((result).cast<String, dynamic>()),
            );
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

class StatusNotifier extends Notifier<StudyStatus> {
  @override
  StudyStatus build() => const StudyStatus();

  // ignore: use_setters_to_change_properties
  void replace(StudyStatus status) => state = status;

  void patchState(String newState, String newDetail) {
    if (newState.isEmpty) return;
    final current = state;
    state = StudyStatus(
      state: newState,
      detail: newDetail.isNotEmpty ? newDetail : current.detail,
      total: current.total,
      done: current.done,
      failed: current.failed,
      courses: current.courses,
    );
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
  @override
  Future<List<Course>> build() async {
    final client = ref.watch(engineClientProvider);
    final connection = ref.watch(connectionProvider);
    if (connection != ConnState.ready) return const [];
    final result = await client.rpc('courses.list', {'refresh': true});
    final items = (result is Map ? result['courses'] as List? : null) ?? const [];
    return items.map((item) => Course.fromJson((item as Map).cast<String, dynamic>())).toList();
  }

  Future<void> refresh() async {
    if (state.isLoading) return; // 防抖：进行中的刷新直接忽略
    state = const AsyncLoading<List<Course>>();
    state = await AsyncValue.guard(() async {
      final result = await ref.read(engineClientProvider).rpc('courses.list', {'refresh': true});
      final items = (result is Map ? result['courses'] as List? : null) ?? const [];
      final courses = items
          .map((item) => Course.fromJson((item as Map).cast<String, dynamic>()))
          .toList();
      // 状态同步：课程列表变化后修剪已失效的选课 ID。
      if (courses.isNotEmpty) {
        ref
            .read(selectedCoursesProvider.notifier)
            .retainAll(courses.map((course) => course.courseId).toSet());
      }
      return courses;
    });
  }
}

final coursesProvider =
    AsyncNotifierProvider<CoursesNotifier, List<Course>>(CoursesNotifier.new);

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
