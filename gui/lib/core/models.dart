/// Value objects exchanged with the Python engine.
library;

class Course {
  const Course({
    required this.courseId,
    required this.clazzId,
    required this.title,
    this.teacher = '',
    this.cpi = '',
  });

  final String courseId;
  final String clazzId;
  final String title;
  final String teacher;
  final String cpi;

  factory Course.fromJson(Map<String, dynamic> json) => Course(
        courseId: '${json['courseId'] ?? ''}',
        clazzId: '${json['clazzId'] ?? ''}',
        title: '${json['title'] ?? ''}',
        teacher: '${json['teacher'] ?? ''}',
        cpi: '${json['cpi'] ?? ''}',
      );
}

class LogEntry {
  const LogEntry({
    required this.ts,
    required this.level,
    required this.logger,
    required this.message,
  });

  final String ts;
  final String level;
  final String logger;
  final String message;

  factory LogEntry.fromJson(Map<String, dynamic> json) => LogEntry(
        ts: '${json['ts'] ?? ''}',
        level: '${json['level'] ?? 'INFO'}',
        logger: '${json['logger'] ?? ''}',
        message: '${json['message'] ?? ''}',
      );
}

/// 一条结构化运行事件（study.task）：章节开始/完成、视频进度、题库统计等。
class TaskActivity {
  const TaskActivity({
    required this.kind,
    required this.phase,
    this.name = '',
    this.course = '',
    this.chapter = '',
    this.progress,
    this.result,
    this.message,
    this.coverRate,
    this.score,
    this.tries,
    this.atTs,
  });

  final String kind; // run | chapter | video | audio | document | work | read | live
  final String phase; // start | progress | done | error | retry | stats | scored | finished
  final String name;
  final String course;
  final String chapter;
  final double? progress;
  final String? result;
  final String? message;
  final double? coverRate;
  final double? score;
  final int? tries;
  final DateTime? atTs;

  bool get isError => phase == 'error';
  bool get isDone => phase == 'done' || phase == 'finished';
  bool get isRetry => phase == 'retry';

  factory TaskActivity.fromJson(Map<String, dynamic> json, [DateTime? at]) => TaskActivity(
        kind: '${json['kind'] ?? ''}',
        phase: '${json['phase'] ?? ''}',
        name: '${json['name'] ?? ''}',
        course: '${json['course'] ?? ''}',
        chapter: '${json['chapter'] ?? ''}',
        progress: (json['progress'] as num?)?.toDouble(),
        result: json['result'] is String ? json['result'] as String : null,
        message: json['message'] is String ? json['message'] as String : null,
        coverRate: (json['cover_rate'] as num?)?.toDouble(),
        score: (json['score'] as num?)?.toDouble(),
        tries: (json['tries'] as num?)?.toInt(),
        atTs: at,
      );

  /// 活动行的一句话描述（供列表/告警复用）。
  String describe() {
    final where = [
      if (course.isNotEmpty) course,
      if (chapter.isNotEmpty) chapter,
    ].join(' · ');
    switch (phase) {
      case 'finished':
        return message ?? '本轮任务已结束';
      case 'stats':
        return '题库覆盖率 ${coverRate!.toStringAsFixed(0)}%（$name）';
      case 'scored':
        return '章节检测成绩 $score 分（$name）';
      case 'retry':
        return '重试中（第 $tries 次）${where.isEmpty ? '' : ' · $where'}';
      default:
        final label = kindLabel(kind);
        final subject = name.isNotEmpty ? name : (chapter.isNotEmpty ? chapter : label);
        return where.isEmpty ? subject : '$where · $subject';
    }
  }

  static String kindLabel(String kind) => switch (kind) {
        'run' => '运行',
        'chapter' => '章节',
        'video' => '视频',
        'audio' => '音频',
        'document' => '文档',
        'work' => '章节检测',
        'read' => '阅读',
        'live' => '直播',
        _ => '任务',
      };
}

class StudyStatus {
  const StudyStatus({
    this.state = 'idle',
    this.detail = '',
    this.total = 0,
    this.done = 0,
    this.failed = 0,
    this.courses = 0,
    this.current,
    this.elapsed = 0,
    this.lastCourseIds = const [],
    this.tikuQueries = 0,
    this.tikuHits = 0,
    this.coverRate,
    this.lastScore,
  });

  final String state;
  final String detail;
  final int total;
  final int done;
  final int failed;
  final int courses;
  /// 引擎侧实时任务快照（轮询恢复用）。
  final TaskActivity? current;
  final int elapsed; // 秒
  final List<String> lastCourseIds;
  final int tikuQueries;
  final int tikuHits;
  final double? coverRate;
  final double? lastScore;

  double get progress => total <= 0 ? 0 : (done / total).clamp(0.0, 1.0);

  bool get isRunning => state == 'running' || state == 'loading' || state == 'paused' || state == 'stopping';

  double? get hitRate => tikuQueries <= 0 ? null : (tikuHits / tikuQueries).clamp(0.0, 1.0);

  StudyStatus copyWith({
    String? state,
    String? detail,
    int? total,
    int? done,
    int? failed,
    int? courses,
    TaskActivity? current,
    int? elapsed,
    List<String>? lastCourseIds,
    int? tikuQueries,
    int? tikuHits,
    double? coverRate,
    double? lastScore,
  }) =>
      StudyStatus(
        state: state ?? this.state,
        detail: detail ?? this.detail,
        total: total ?? this.total,
        done: done ?? this.done,
        failed: failed ?? this.failed,
        courses: courses ?? this.courses,
        current: current ?? this.current,
        elapsed: elapsed ?? this.elapsed,
        lastCourseIds: lastCourseIds ?? this.lastCourseIds,
        tikuQueries: tikuQueries ?? this.tikuQueries,
        tikuHits: tikuHits ?? this.tikuHits,
        coverRate: coverRate ?? this.coverRate,
        lastScore: lastScore ?? this.lastScore,
      );

  factory StudyStatus.fromJson(Map<String, dynamic> json) {
    final currentJson = json['current'];
    final tikuStats = json['tiku_stats'];
    var queries = 0;
    var hits = 0;
    if (tikuStats is Map) {
      for (final value in tikuStats.values) {
        if (value is Map) {
          queries += (value['queries'] as num?)?.toInt() ?? 0;
          hits += (value['hits'] as num?)?.toInt() ?? 0;
        }
      }
    }
    return StudyStatus(
      state: '${json['state'] ?? 'idle'}',
      detail: '${json['detail'] ?? ''}',
      total: (json['total'] as num?)?.toInt() ?? 0,
      done: (json['done'] as num?)?.toInt() ?? 0,
      failed: (json['failed'] as num?)?.toInt() ?? 0,
      courses: (json['courses'] as num?)?.toInt() ?? 0,
      current: currentJson is Map
          ? TaskActivity.fromJson((currentJson).cast<String, dynamic>())
          : null,
      elapsed: (json['elapsed'] as num?)?.toInt() ?? 0,
      lastCourseIds: ((json['last_course_ids'] as List?) ?? const [])
          .map((item) => '$item')
          .toList(),
      tikuQueries: queries,
      tikuHits: hits,
    );
  }
}

class ManualQuestion {
  const ManualQuestion({
    required this.batchId,
    required this.index,
    required this.title,
    required this.type,
    required this.options,
  });

  final String batchId;
  final int index;
  final String title;
  final String type;
  final String options;

  List<String> get optionList => options
      .split('\n')
      .map((line) => line.trim())
      .where((line) => line.isNotEmpty)
      .toList();

  String get typeLabel {
    switch (type) {
      case 'single':
        return '单选题';
      case 'multiple':
        return '多选题';
      case 'judgement':
        return '判断题';
      case 'completion':
        return '填空题';
      default:
        return '题目';
    }
  }
}
