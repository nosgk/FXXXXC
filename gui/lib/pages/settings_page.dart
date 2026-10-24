import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/engine_client.dart';
import '../state.dart';

class _Field {
  const _Field(
    this.key,
    this.label, {
    this.obscure = false,
    this.options,
    this.boolField = false,
  });

  final String key;
  final String label;
  final bool obscure;
  final List<String>? options;
  final bool boolField;
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
    _Field('speed', '视频倍速（1.0-2.0）'),
    _Field('jobs', '并发章节数'),
    _Field('notopen_action', '未开放任务点处理', options: ['retry', 'ask', 'continue']),
    _Field('retry_interval', '重试间隔（秒）'),
    _Field('chapter_max_tries', '章节最大重试次数'),
    _Field('work_redo_enabled', '章节检测答错后自动重做', boolField: true),
    _Field('work_max_retries', '章节检测最大重做次数'),
    _Field('add_learning_count', '完成后增加章节学习次数', boolField: true),
    _Field('target_count', '学习次数目标'),
    _Field('learning_count_interval', '学习次数访问间隔（秒）'),
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
    _Field('cover_rate', '最低题库覆盖率（0-1）'),
    _Field('delay', '搜题间隔（秒）'),
    _Field('endpoint', '大模型 endpoint（AI）'),
    _Field('key', '大模型 key（AI）', obscure: true),
    _Field('model', '大模型 model（AI）'),
    _Field('min_interval_seconds', '大模型请求间隔（秒）'),
    _Field('http_proxy', '大模型代理'),
    _Field('siliconflow_key', '硅基流动 key', obscure: true),
    _Field('siliconflow_model', '硅基流动 model'),
  ]),
  _Section('通知', 'notification', [
    _Field('provider', '通知 provider', options: ['ServerChan', 'Qmsg', 'Bark', 'Telegram']),
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
  bool _saving = false;
  bool _dark = false;

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void _syncFromConfig(Map<String, dynamic> config) {
    for (final section in _sections) {
      final values = (config[section.sectionKey] as Map?)?.cast<String, dynamic>() ?? const {};
      for (final field in section.fields) {
        final key = '${section.sectionKey}.${field.key}';
        final value = '${values[field.key] ?? ''}';
        _initial[key] = value;
        final controller = _controllers[key];
        if (controller == null) {
          _controllers[key] = TextEditingController(text: value);
        } else if (controller.text != value) {
          controller.text = value;
        }
      }
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final patch = <String, Map<String, String>>{};
    for (final section in _sections) {
      for (final field in section.fields) {
        final key = '${section.sectionKey}.${field.key}';
        final value = _controllers[key]?.text ?? '';
        if (value != (_initial[key] ?? '')) {
          patch.putIfAbsent(section.sectionKey, () => {})[field.key] = value;
        }
      }
    }
    try {
      if (patch.isNotEmpty) {
        await ref.read(engineClientProvider).rpc('config.set', {'config': patch});
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(patch.isEmpty ? '没有需要保存的修改' : '已保存 ${patch.length} 个配置节')),
        );
      }
      ref.invalidate(configProvider);
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
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
    configAsync.whenData(_syncFromConfig);

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Card(
          child: SwitchListTile(
            title: const Text('深色主题'),
            subtitle: const Text('跟随系统时以系统为准，打开后强制深色'),
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
                  Text(section.title, style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 12),
                  for (final field in section.fields)
                    _buildField(context, section.sectionKey, field),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 16),
        Row(
          children: [
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: const Icon(Icons.save_outlined),
              label: const Text('保存配置'),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: () => _test('tiku.test'),
              icon: const Icon(Icons.quiz_outlined),
              label: const Text('测试题库'),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: () => _test('notification.test'),
              icon: const Icon(Icons.notifications_outlined),
              label: const Text('测试通知'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildField(BuildContext context, String sectionKey, _Field field) {
    final key = '$sectionKey.${field.key}';
    final controller = _controllers.putIfAbsent(key, () => TextEditingController());

    if (field.boolField) {
      final value = controller.text.trim().toLowerCase() == 'true';
      return SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(field.label),
        value: value,
        onChanged: (next) => setState(() => controller.text = next ? 'true' : 'false'),
      );
    }

    if (field.options != null) {
      final current = controller.text;
      return DropdownButtonFormField<String>(
        initialValue: current.isEmpty ? null : current,
        decoration: InputDecoration(labelText: field.label),
        items: [
          for (final option in field.options!)
            DropdownMenuItem(value: option, child: Text(option)),
        ],
        onChanged: (value) => setState(() => controller.text = value ?? ''),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        controller: controller,
        obscureText: field.obscure,
        decoration: InputDecoration(
          labelText: field.label,
        ),
      ),
    );
  }
}
