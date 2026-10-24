import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/engine_client.dart';
import '../state.dart';

/// 字段级 schema（与引擎 fxxxxc/engine/service.py 的校验保持一致）。
/// 只做轻量前端提示；权威校验在引擎 config.set，失败会整单拒绝。
class _Field {
  const _Field(
    this.key,
    this.label, {
    this.obscure = false,
    this.options,
    this.boolField = false,
    this.helper,
    this.numeric,
  });

  final String key;
  final String label;
  final bool obscure;
  final List<String>? options;
  final bool boolField;
  final String? helper;
  final _NumericRange? numeric;
}

class _NumericRange {
  const _NumericRange(this.min, this.max, {this.isInt = false});
  final num min;
  final num max;
  final bool isInt;

  String get hint => isInt ? '$min~$max' : '$min~$max';
}

class _Section {
  const _Section(this.title, this.sectionKey, this.fields);
  final String title;
  final String sectionKey;
  final List<_Field> fields;
}

const _sections = [
  _Section('账号', 'common', [
    _Field('username', '手机号'),
    _Field('password', '密码', obscure: true),
    _Field('use_cookies', '使用 cookies 登录（忽略账号密码）', boolField: true),
  ]),
  _Section('学习', 'common', [
    _Field('speed', '视频倍速',
        numeric: _NumericRange(1.0, 2.0), helper: '1.0 ~ 2.0，保存时自动夹取'),
    _Field('jobs', '并发章节数',
        numeric: _NumericRange(1, 16, isInt: true), helper: '1 ~ 16'),
    _Field('notopen_action', '未开放任务点处理', options: ['retry', 'ask', 'continue']),
    _Field('retry_interval', '重试间隔（秒）', numeric: _NumericRange(0.0, 60.0)),
    _Field('chapter_max_tries', '章节最大重试次数',
        numeric: _NumericRange(1, 20, isInt: true)),
    _Field('work_redo_enabled', '章节检测答错后自动重做', boolField: true),
    _Field('work_max_retries', '章节检测最大重做次数',
        numeric: _NumericRange(0, 10, isInt: true)),
    _Field('add_learning_count', '完成后增加章节学习次数', boolField: true),
    _Field('target_count', '学习次数目标', numeric: _NumericRange(1, 10000, isInt: true)),
    _Field('learning_count_interval', '学习次数访问间隔（秒）',
        numeric: _NumericRange(0.0, 3600.0), helper: '默认 30，模拟前端心跳'),
  ]),
  _Section('题库', 'tiku', [
    _Field(
      'provider',
      'provider（可逗号分隔多个回退）',
      options: [
        'TikuYanxi',
        'TikuGo',
        'TikuLike',
        'TikuAdapter',
        'AI',
        'SiliconFlow',
        'TikuManual',
      ],
    ),
    _Field('tokens', '题库 tokens（逗号分隔）'),
    _Field('submit', '达到覆盖率后自动提交', boolField: true),
    _Field('cover_rate', '最低题库覆盖率',
        numeric: _NumericRange(0.0, 1.0), helper: '0 ~ 1，例如 0.9'),
    _Field('delay', '搜题间隔（秒）', numeric: _NumericRange(0.0, 60.0)),
    _Field('endpoint', '大模型 endpoint（AI）',
        helper: '兼容 OpenAI 格式，本地模型可用 http://127.0.0.1:端口/v1'),
    _Field('key', '大模型 key（AI）', obscure: true),
    _Field('model', '大模型 model（AI）'),
    _Field('min_interval_seconds', '大模型请求间隔（秒）',
        numeric: _NumericRange(0, 600, isInt: true)),
    _Field('http_proxy', '大模型代理'),
    _Field('siliconflow_key', '硅基流动 key', obscure: true),
    _Field('siliconflow_model', '硅基流动 model'),
  ]),
  _Section('通知', 'notification', [
    _Field('provider', '通知 provider',
        options: ['ServerChan', 'Qmsg', 'Bark', 'Telegram']),
    _Field('url', '通知 URL', obscure: true),
    _Field('tg_chat_id', 'Telegram chat_id', obscure: true),
  ]),
];

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  final _controllers = <String, TextEditingController>{};
  final _initial = <String, String>{};
  /// 用户改过、尚未保存的字段。引擎配置刷新时绝不能覆盖这些字段，
  /// 否则表现为"开关点不了/输入被吞"。
  final _dirty = <String>{};
  bool _saving = false;
  bool _dark = false;

  bool get _hasChanges => _dirty.isNotEmpty;

  @override
  void initState() {
    super.initState();
    // 只在"引擎配置真的变化"时同步远端值（保存回读 / 初始加载），
    // 绝不在 build 里每帧覆写控制器。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.listenManual(configProvider, (previous, next) {
        if (identical(previous?.value, next.value)) return;
        next.whenData(_applyRemote);
      }, fireImmediately: true);
    });
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void _applyRemote(Map<String, dynamic> config) {
    for (final section in _sections) {
      final values = (config[section.sectionKey] as Map?)?.cast<String, dynamic>() ?? const {};
      for (final field in section.fields) {
        final key = _keyOf(section.sectionKey, field.key);
        final value = '${values[field.key] ?? ''}';
        _initial[key] = value;
        final controller = _controllers[key];
        if (controller == null) {
          _controllers[key] = TextEditingController(text: value);
        } else if (!_dirty.contains(key) && controller.text != value) {
          controller.text = value;
        }
      }
    }
    if (mounted) setState(() {});
  }

  String _keyOf(String section, String field) => '$section.$field';

  void _markDirty(String key, String value) {
    _controllers[key]!.text = value;
    if (value != (_initial[key] ?? '')) {
      _dirty.add(key);
    } else {
      _dirty.remove(key);
    }
    setState(() {});
  }

  Map<String, String>? _clientValidate() {
    for (final section in _sections) {
      for (final field in section.fields) {
        final field_ = field.numeric;
        if (field_ == null) continue;
        final key = _keyOf(section.sectionKey, field.key);
        final text = _controllers[key]?.text.trim() ?? '';
        if (text.isEmpty) continue;
        final value = field_.isInt ? int.tryParse(text) : double.tryParse(text);
        if (value == null || value < field_.min || value > field_.max) {
          return {
            'key': key,
            'message': '${field.label} 需为${field_.isInt ? '整数' : '数字'}（${field_.hint}）',
          };
        }
      }
    }
    return null;
  }

  Future<void> _save() async {
    final invalid = _clientValidate();
    if (invalid != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(invalid['message']!)),
      );
      return;
    }
    setState(() => _saving = true);
    final patch = <String, Map<String, String>>{};
    for (final section in _sections) {
      for (final field in section.fields) {
        final key = _keyOf(section.sectionKey, field.key);
        final value = _controllers[key]?.text ?? '';
        if (_dirty.contains(key)) {
          patch.putIfAbsent(section.sectionKey, () => {})[field.key] = value;
        }
      }
    }
    try {
      if (patch.isNotEmpty) {
        await ref.read(configProvider.notifier).save(patch);
        _dirty.clear(); // 保存后由 notifier 回读新值，形成双向同步闭环
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(patch.isEmpty ? '没有需要保存的修改' : '已保存 ${patch.length} 个配置节')),
        );
      }
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存失败：${error.message}')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _test(String method) async {
    try {
      final result = await ref.read(engineClientProvider).rpc(method);
      final ok = result is Map && result['ok'] == true;
      final message = result is Map ? '${result['message'] ?? ''}' : '';
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(ok ? '测试通过：$message' : '测试失败：$message')),
        );
      }
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final configAsync = ref.watch(configProvider);

    return Column(
      children: [
        Expanded(
          child: Stack(
            children: [
              ListView(
                padding: const EdgeInsets.fromLTRB(24, 24, 24, 8),
                children: [
                  Card(
                    child: SwitchListTile(
                      title: const Text('深色主题'),
                      subtitle: const Text('关闭时跟随系统'),
                      value: _dark,
                      onChanged: (value) {
                        setState(() => _dark = value);
                        ref.read(themeModeProvider.notifier).set(
                              value ? ThemeMode.dark : ThemeMode.system,
                            );
                      },
                    ),
                  ),
            for (final section in _sections) ...[
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(section.title, style: Theme.of(context).textTheme.titleMedium),
                          const Spacer(),
                          if (_dirty.any((key) => key.startsWith('${section.sectionKey}.')))
                            Tooltip(
                              message: '有未保存修改',
                              child: Icon(Icons.circle, size: 8,
                                  color: Theme.of(context).colorScheme.primary),
                            ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      for (final field in section.fields)
                        _buildField(context, section.sectionKey, field),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 24),
                ],
              ),
            if (configAsync.isLoading && _controllers.isEmpty)
              const Positioned.fill(
                child: ColoredBox(
                  color: Color(0x66000000),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ),
            ],
          ),
        ),
        // 固定操作栏：保存/测试常驻可见，不随长列表滚出视口。
        Container(
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 16),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerLow,
            border: Border(top: BorderSide(color: Theme.of(context).dividerTheme.color ?? Colors.grey)),
          ),
          child: Row(
            children: [
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(width: 16, height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.save_outlined),
                label: Text(_hasChanges ? '保存配置（${_dirty.length} 项）' : '保存配置'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _saving ? null : () => _test('tiku.test'),
                icon: const Icon(Icons.quiz_outlined),
                label: const Text('测试题库'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _saving ? null : () => _test('notification.test'),
                icon: const Icon(Icons.notifications_outlined),
                label: const Text('测试通知'),
              ),
              const Spacer(),
              if (_hasChanges)
                Text('有未保存修改', style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildField(BuildContext context, String sectionKey, _Field field) {
    final key = _keyOf(sectionKey, field.key);
    final controller = _controllers.putIfAbsent(key, () => TextEditingController());

    if (field.boolField) {
      final value = controller.text.trim().toLowerCase() == 'true';
      return SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(field.label),
        value: value,
        onChanged: (next) => _markDirty(key, next ? 'true' : 'false'),
      );
    }

    if (field.options != null) {
      final current = controller.text;
      final validCurrent = field.options!.contains(current) ? current : null;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: DropdownButtonFormField<String>(
          initialValue: validCurrent,
          decoration: InputDecoration(
            labelText: field.label,
            helperText: field.helper,
            errorText: current.isNotEmpty && validCurrent == null
                ? '当前值 "$current" 不在可选列表内，选择后将覆盖'
                : null,
          ),
          items: [
            for (final option in field.options!)
              DropdownMenuItem(value: option, child: Text(option)),
          ],
          onChanged: (value) => _markDirty(key, value ?? ''),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        controller: controller,
        obscureText: field.obscure,
        onChanged: (value) => _markDirty(key, value),
        decoration: InputDecoration(
          labelText: field.label,
          helperText: field.helper,
        ),
      ),
    );
  }
}
