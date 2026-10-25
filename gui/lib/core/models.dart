/// Value objects exchanged with the Python engine.
library;

class Course {
  const Course({
    required this.courseId,
    required this.clazzId,
    required this.title,
    this.teacher = '',
    this.cpi = '',
    this.cover = '',
    this.notOpen = false,
  });

  final String courseId;
  final String clazzId;
  final String title;
  final String teacher;
  final String cpi;
  /// 课程封面地址（引擎 best-effort 提取，可能为空 → GUI 回退占位图）。
  final String cover;
  /// 平台侧未开放（不可进入学习）的课程。
  final bool notOpen;

  /// 课程详情/章节状态的缓存键。
  String get detailKey => '$courseId|$clazzId|$cpi';

  factory Course.fromJson(Map<String, dynamic> json) => Course(
        courseId: '${json['courseId'] ?? ''}',
        clazzId: '${json['clazzId'] ?? ''}',
        title: '${json['title'] ?? ''}',
        teacher: '${json['teacher'] ?? ''}',
        cpi: '${json['cpi'] ?? ''}',
        cover: '${json['cover'] ?? ''}',
        notOpen: json['notOpen'] == true || json['notOpen'] == 'true',
      );

  Map<String, dynamic> toJson() => {
        'courseId': courseId,
        'clazzId': clazzId,
        'title': title,
        'teacher': teacher,
        'cpi': cpi,
        'cover': cover,
        'notOpen': notOpen,
      };
}

/// 单个章节的状态（course.detail 返回）。
class ChapterStatus {
  const ChapterStatus({
    required this.index,
    required this.title,
    required this.finished,
    required this.jobCount,
    required this.needUnlock,
  });

  final int index;
  final String title;
  final bool finished;
  final int jobCount;
  final bool needUnlock;

  factory ChapterStatus.fromJson(Map<String, dynamic> json) => ChapterStatus(
        index: (json['index'] as num?)?.toInt() ?? 0,
        title: '${json['title'] ?? ''}',
        finished: json['finished'] == true,
        jobCount: (json['job_count'] as num?)?.toInt() ?? 0,
        needUnlock: json['need_unlock'] == true,
      );
}

/// 一门课程的章节状态明细。
class CourseDetail {
  const CourseDetail({
    required this.courseId,
    required this.clazzId,
    required this.chapters,
    required this.total,
    required this.finished,
    required this.locked,
    required this.hasLocked,
  });

  final String courseId;
  final String clazzId;
  final List<ChapterStatus> chapters;
  final int total;
  final int finished;
  final int locked;
  final bool hasLocked;

  double? get progress => total <= 0 ? null : (finished / total).clamp(0.0, 1.0);

  factory CourseDetail.fromJson(Map<String, dynamic> json) {
    final rawChapters = (json['chapters'] as List?) ?? const [];
    return CourseDetail(
      courseId: '${json['course_id'] ?? ''}',
      clazzId: '${json['clazz_id'] ?? ''}',
      chapters: rawChapters
          .whereType<Map>()
          .map((item) => ChapterStatus.fromJson(item.cast<String, dynamic>()))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? 0,
      finished: (json['finished'] as num?)?.toInt() ?? 0,
      locked: (json['locked'] as num?)?.toInt() ?? 0,
      hasLocked: json['has_locked'] == true,
    );
  }
}

/// 本轮运行中单门课程的实时进度（study.status courses_progress）。
class CourseProgress {
  const CourseProgress({
    required this.courseId,
    required this.title,
    required this.total,
    required this.done,
    required this.failed,
  });

  final String courseId;
  final String title;
  final int total;
  final int done;
  final int failed;

  bool get isRunning => done < total;

  double get progress => total <= 0 ? 0 : (done / total).clamp(0.0, 1.0);

  factory CourseProgress.fromJson(Map<String, dynamic> json) => CourseProgress(
        courseId: '${json['course_id'] ?? ''}',
        title: '${json['title'] ?? ''}',
        total: (json['total'] as num?)?.toInt() ?? 0,
        done: (json['done'] as num?)?.toInt() ?? 0,
        failed: (json['failed'] as num?)?.toInt() ?? 0,
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
    this.count,
    this.target,
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
  /// 学习次数阶段进度：count/target。
  final int? count;
  final int? target;
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
        count: (json['count'] as num?)?.toInt(),
        target: (json['target'] as num?)?.toInt(),
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
        return '答题覆盖率 ${coverRate!.toStringAsFixed(0)}%（$name）';
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
        'learn' => '学习次数',
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
    this.bankStats = const [],
    this.coursesProgress = const [],
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
  /// 每个题库源的命中统计（多题库梯度回退时逐源展示）。
  final List<BankStat> bankStats;
  /// 本轮运行每门课程的实时进度。
  final List<CourseProgress> coursesProgress;
  final double? coverRate;
  final double? lastScore;

  /// 按课程ID索引的本轮进度，课程页徽标/进度条直接取用。
  Map<String, CourseProgress> get progressByCourse => {
        for (final item in coursesProgress) item.courseId: item,
      };

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
    List<BankStat>? bankStats,
    List<CourseProgress>? coursesProgress,
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
        bankStats: bankStats ?? this.bankStats,
        coursesProgress: coursesProgress ?? this.coursesProgress,
        coverRate: coverRate ?? this.coverRate,
        lastScore: lastScore ?? this.lastScore,
      );

  factory StudyStatus.fromJson(Map<String, dynamic> json) {
    final currentJson = json['current'];
    final tikuStats = json['tiku_stats'];
    var queries = 0;
    var hits = 0;
    final banks = <BankStat>[];
    if (tikuStats is Map) {
      tikuStats.forEach((key, value) {
        if (value is! Map) return;
        final bankQueries = (value['queries'] as num?)?.toInt() ?? 0;
        final bankHits = (value['hits'] as num?)?.toInt() ?? 0;
        queries += bankQueries;
        hits += bankHits;
        banks.add(BankStat(
          name: '$key',
          queries: bankQueries,
          hits: bankHits,
        ));
      });
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
      bankStats: banks,
      coursesProgress: ((json['courses_progress'] as List?) ?? const [])
          .whereType<Map>()
          .map((item) => CourseProgress.fromJson(item.cast<String, dynamic>()))
          .toList(),
    );
  }
}

/// 单个题库源的命中统计（来自引擎 TikuFallback.get_stats）。
class BankStat {
  const BankStat({required this.name, required this.queries, required this.hits});

  final String name;
  final int queries;
  final int hits;

  double? get hitRate => queries <= 0 ? null : (hits / queries).clamp(0.0, 1.0);
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
