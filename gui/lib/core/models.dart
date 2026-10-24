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

class StudyStatus {
  const StudyStatus({
    this.state = 'idle',
    this.detail = '',
    this.total = 0,
    this.done = 0,
    this.failed = 0,
    this.courses = 0,
  });

  final String state;
  final String detail;
  final int total;
  final int done;
  final int failed;
  final int courses;

  double get progress => total <= 0 ? 0 : (done / total).clamp(0.0, 1.0);

  factory StudyStatus.fromJson(Map<String, dynamic> json) => StudyStatus(
        state: '${json['state'] ?? 'idle'}',
        detail: '${json['detail'] ?? ''}',
        total: (json['total'] as num?)?.toInt() ?? 0,
        done: (json['done'] as num?)?.toInt() ?? 0,
        failed: (json['failed'] as num?)?.toInt() ?? 0,
        courses: (json['courses'] as num?)?.toInt() ?? 0,
      );
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
