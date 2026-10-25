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
    this.multiline = false,
  });

  final String key;
  final String label;
  final bool obscure;
  final List<String>? options;
  final bool boolField;
  final String? helper;
  final _NumericRange? numeric;
  /// 多行文本域（用于粘贴 JSON 配置）。
  final bool multiline;
}

class _NumericRange {
  const _NumericRange(this.min, this.max, {this.isInt = false});
  final num min;
  final num max;
  final bool isInt;

  String get hint => '$min~$max';
}

class _Section {
  const _Section(this.title, this.sectionKey, this.fields, {this.intro});
  final String title;
  final String sectionKey;
  final List<_Field> fields;
  final String? intro;
}

/// 答题源元信息：显示名 + 一句话说明（小白选型用）。
class _ProviderMeta {
  const _ProviderMeta(this.display, this.desc);
  final String display;
  final String desc;
}

const _bankProviders = <String, _ProviderMeta>{
  'TikuOcs': _ProviderMeta('OCS 兼容答题源', '粘贴 ocsjs 题库配置 JSON 即用，鉴权内嵌免单独配置'),
  'TikuYanxi': _ProviderMeta('言溪题库', '公共在线题库，需 token，按次计费查询'),
  'TikuGo': _ProviderMeta('GO题（网课小工具）', '公共在线题库，需 Authorization 鉴权码'),
  'TikuLike': _ProviderMeta('LIKE 知识库', '支持图片题目识别的在线题库'),
  'TikuAdapter': _ProviderMeta('自定义接口', '对接自建题库服务的通用适配器'),
  'AI': _ProviderMeta('AI 大模型', '任意 OpenAI 兼容接口：DeepSeek、Kimi、GLM、本地模型等'),
  'SiliconFlow': _ProviderMeta('硅基流动', '硅基流动官方接口，直接填 key 即可'),
  'TikuManual': _ProviderMeta('手动作答', '遇到题目弹出窗口人工作答，最稳妥但需人值守'),
};

/// 每种答题源只显示自己的配置项（选择 A 源就只显示 A 源的设置）。
const _bankProviderFields = <String, List<_Field>>{
  'TikuOcs': [
    _Field('ocs_wrappers', 'OCS 题库配置 JSON', multiline: true,
        helper: '粘贴 ocsjs「题库配置」的 JSON（[{name,url,data,...}]）；'
            '鉴权通常已内嵌在配置里，无需额外 token。'
            '其中的 handler(JS) 不会被执行，按 answer_path 或智能提取解析'),
    _Field('ocs_answer_path', '答案提取路径（可选）',
        helper: '点路径如 data.answer；留空使用智能提取'),
  ],
  'TikuYanxi': [
    _Field('tokens', '题库 Token',
        helper: '在 tk.enncy.cn 个人中心获取，多个 token 用英文逗号分隔，可自动轮换'),
  ],
  'TikuGo': [
    _Field('go_authorization', 'Authorization 鉴权码', helper: '网课小工具后台获取'),
    _Field('go_min_interval', '请求间隔（秒）', numeric: _NumericRange(0.0, 60.0),
        helper: '两次搜题的最小间隔，过快会被限流'),
    _Field('go_retry_times', '失败重试次数', numeric: _NumericRange(1, 10, isInt: true)),
    _Field('go_retry_backoff', '重试退避系数', numeric: _NumericRange(1.0, 10.0),
        helper: '每次重试等待 = 系数 × 已重试次数'),
  ],
  'TikuLike': [
    _Field('tokens', '题库 Token', helper: '多个 token 用英文逗号分隔'),
    _Field('likeapi_search', '启用知识库搜索', boolField: true),
    _Field('likeapi_vision', '启用图片识别', boolField: true),
    _Field('likeapi_model', '识别模型', helper: '默认 glm-4.5-air'),
    _Field('likeapi_retry', '查询失败自动重试', boolField: true),
    _Field('likeapi_retry_times', '重试次数', numeric: _NumericRange(1, 10, isInt: true)),
  ],
  'TikuAdapter': [
    _Field('url', '接口地址', helper: '自建题库服务的完整 URL，例如 http://127.0.0.1:8080/search'),
  ],
  'AI': [
    _Field('endpoint', '接口地址 endpoint',
        helper: '兼容 OpenAI 格式，通常以 /v1 结尾；本地模型可用 http://127.0.0.1:端口/v1'),
    _Field('key', 'API Key', obscure: true, helper: '服务商控制台生成的密钥'),
    _Field('model', '模型名称', helper: '例如 deepseek-chat、glm-4.5-air、qwen-plus'),
    _Field('min_interval_seconds', '请求间隔（秒）',
        numeric: _NumericRange(0, 600, isInt: true), helper: '避免触发服务商限流'),
    _Field('http_proxy', '代理地址', helper: '如 http://127.0.0.1:7890，留空直连'),
    _Field('extra_body', '额外请求参数 extra_body',
        helper: 'JSON 对象；默认 {"thinking":{"type":"disabled"}} 关闭深度思考，报错可设为 {}'),
    _Field('json_mode', '强制 JSON 输出', boolField: true,
        helper: '由服务端保证输出合法 JSON；部分中转不支持，报错请关闭'),
  ],
  'SiliconFlow': [
    _Field('siliconflow_key', 'API Key', obscure: true, helper: 'siliconflow.cn 控制台获取'),
    _Field('siliconflow_model', '模型名称',
        helper: '如 deepseek-ai/DeepSeek-R1，需带组织前缀'),
    _Field('siliconflow_endpoint', '接口地址',
        helper: '默认官方地址，一般无需修改'),
  ],
  'TikuManual': [
    _Field('manual_mode_default', '默认作答方式',
        options: ['batch', 'single'], helper: 'batch=一次弹出一批题目，single=逐题弹出'),
    _Field('manual_mode_separator', '批量答案分隔符',
        options: [';', ',', ' ', 'tab', '\\n', '；', '，'],
        helper: '批量作答时用什么分隔多个答案'),
  ],
};

/// 题库实例自身的元字段（每种源都有）。
const _bankBaseFields = <_Field>[
  _Field('enabled', '启用', boolField: true),
  _Field('priority', '回退顺序（数值小的先查询）',
      numeric: _NumericRange(0, 999, isInt: true)),
  _Field('name', '实例名称', helper: '仅用于在本页展示，方便区分多个实例'),
  _Field('provider', '答题源类型'),
];

const _bankProviderOptions = ['TikuYanxi', 'TikuGo', 'TikuLike', 'TikuAdapter', 'AI', 'SiliconFlow', 'TikuManual'];

/// 通知源：全部走 webhook URL，Telegram 额外要 chat_id。
const _notificationSection = _Section('通知', 'notification', [
  _Field('provider', '通知服务'),
  _Field('url', '通知地址 URL', obscure: true,
      helper: '各服务的 SendKey / 推送地址，从服务后台复制'),
  _Field('tg_chat_id', 'Telegram chat_id', obscure: true,
      helper: '向 @userinfobot 发消息可查看自己的 chat_id'),
], intro: '任务结束/出错时推送一条消息提醒你。不需要就保持「通知服务」为空。');

const _notificationProviderMeta = <String, String>{
  'ServerChan': 'Server酱·turbo，推送到微信',
  'Qmsg': 'Qmsg酱，推送到 QQ',
  'Bark': 'Bark，推送到 iPhone',
  'Telegram': 'Telegram Bot 推送',
};

const _fixedSections = [
  _Section('账号', 'common', [
    _Field('username', '手机号', helper: '超星学习通登录手机号'),
    _Field('password', '密码', obscure: true),
    _Field('use_cookies', '使用 cookies 登录（忽略账号密码）', boolField: true,
        helper: '已在本机浏览器登录过、或账号开了验证时使用；引擎会读取 cookies.txt'),
  ], intro: '用于登录超星平台。二选一：填手机号 + 密码，或打开 cookies 登录。'),
  _Section('学习', 'common', [
    _Field('speed', '视频倍速', numeric: _NumericRange(1.0, 2.0),
        helper: '1.0 ~ 2.0，保存时自动夹取；平台最高 2x'),
    _Field('jobs', '并发章节数', numeric: _NumericRange(1, 16, isInt: true),
        helper: '同时学习的章节数，越大越快也越容易被风控，建议 2~6'),
    _Field('notopen_action', '未开放任务点处理',
        options: ['retry', 'ask', 'continue'],
        helper: 'retry=稍后重试 / ask=暂停询问 / continue=跳过'),
    _Field('retry_interval', '重试间隔（秒）', numeric: _NumericRange(0.0, 60.0),
        helper: '失败或未开放章节的重试等待时间'),
    _Field('chapter_max_tries', '章节最大重试次数', numeric: _NumericRange(1, 20, isInt: true)),
    _Field('work_redo_enabled', '章节检测答错后自动重做', boolField: true,
        helper: '仅允许作答一次的课程请保持关闭，否则重做轮无法获取题目'),
    _Field('work_max_retries', '章节检测最大重做轮数', numeric: _NumericRange(0, 10, isInt: true)),
    _Field('add_learning_count', '完成后增加章节学习次数', boolField: true,
        helper: '部分课程要求学习次数达标，开启后任务完成后补次数'),
    _Field('target_count', '学习次数目标', numeric: _NumericRange(1, 10000, isInt: true)),
    _Field('learning_count_interval', '学习次数访问间隔（秒）',
        numeric: _NumericRange(0.0, 3600.0), helper: '默认 30，模拟前端心跳，不建议低于 10'),
  ], intro: '控制学习行为：速度、并发、重试与重做策略。保守设置更安全。'),
];

/// 全局答题源设置：作用于所有答题源实例的公共参数。
const _tikuGlobalSection = _Section('答题全局设置', 'tiku', [
  _Field('submit', '达到覆盖率后自动提交', boolField: true,
      helper: '关闭=只保存答案不提交（最安全）；开启=覆盖率达标后交卷'),
  _Field('cover_rate', '最低题库覆盖率', numeric: _NumericRange(0.0, 1.0),
      helper: '0 ~ 1，例如 0.9 表示 90% 题目有答案才允许提交'),
  _Field('delay', '搜题间隔（秒）', numeric: _NumericRange(0.0, 60.0),
      helper: '每次查题之间的停顿，降低请求频率'),
  _Field('check_llm_connection', '启动时检查大模型连接', boolField: true,
      helper: '仅 AI / 硅基流动源生效'),
  _Field('true_list', '判断题「正确」别名', helper: '逗号分隔，题库返回这些词视为正确'),
  _Field('false_list', '判断题「错误」别名', helper: '逗号分隔，题库返回这些词视为错误'),
  _Field('insecure_skip_verify', '跳过 TLS 证书校验', boolField: true,
      helper: '仅自签名/内网环境使用，默认关闭'),
  _Field('provider', '兼容模式 provider（可逗号分隔多个）',
      options: _bankProviderOptions,
      helper: '旧版单配置模式；配置了上方答题源实例后此项被忽略'),
], intro: '这些参数对所有答题源生效：提交策略、覆盖率门槛与判断题词表。');

class _BankMeta {
  _BankMeta(this.sectionId, {this.localOnly = false});

  final String sectionId;
  bool localOnly;
}

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
  final _banks = <String, _BankMeta>{};
  final _bankOrder = <String>[];
  final _removedBanks = <String>{};
  /// 收起/展开的答题源卡片（未展开即收起态：只显示摘要行）。
  final _expandedBanks = <String>{};
  bool _saving = false;
  bool _dark = false;

  bool get _hasChanges => _dirty.isNotEmpty || _removedBanks.isNotEmpty;

  static const _bankSectionPrefix = 'tiku_bank.';

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

  // ------------------------------------------------------------- 数据同步

  void _applyRemote(Map<String, dynamic> config) {
    for (final section in _fixedSections) {
      _syncSection(config, section.sectionKey, section.fields);
    }
    _syncSection(config, _tikuGlobalSection.sectionKey, _tikuGlobalSection.fields);
    _syncSection(config, _notificationSection.sectionKey, _notificationSection.fields);

    // 题库实例：先同步元字段（provider 决定后续显示哪些字段），再同步专属字段。
    final remoteBanks = <String>{};
    config.forEach((key, value) {
      if (!key.startsWith(_bankSectionPrefix)) return;
      if (value is! Map) return;
      remoteBanks.add(key);
      final meta = _banks.putIfAbsent(key, () => _BankMeta(key));
      meta.localOnly = false;
      if (!_bankOrder.contains(key)) {
        _bankOrder.add(key);
      }
      final values = value.cast<String, dynamic>();
      for (final field in _bankBaseFields) {
        _syncField(key, field, '${values[field.key] ?? ''}');
      }
      for (final field in _providerFieldsFor(_text(_keyOf(key, 'provider')))) {
        _syncField(key, field, '${values[field.key] ?? ''}');
      }
    });
    // 远端已删除且无未保存修改的实例，本地一并移除。
    for (final id in List.of(_bankOrder)) {
      final meta = _banks[id];
      if (meta == null) continue;
      final hasDirty = _dirty.any((key) => key.startsWith('$id.'));
      if (!remoteBanks.contains(id) && !meta.localOnly && !hasDirty) {
        _dropBank(id);
      }
    }
    _sortBanks();
    if (mounted) setState(() {});
  }

  void _sortBanks() {
    int priorityOf(String id) =>
        int.tryParse(_text(_keyOf(id, 'priority')).trim()) ?? 0;
    _bankOrder.sort((a, b) {
      final byPriority = priorityOf(a).compareTo(priorityOf(b));
      return byPriority != 0 ? byPriority : a.compareTo(b);
    });
  }

  List<_Field> _providerFieldsFor(String provider) =>
      _bankProviderFields[provider] ?? const <_Field>[];

  void _syncSection(
    Map<String, dynamic> config,
    String sectionKey,
    List<_Field> fields,
  ) {
    final values = (config[sectionKey] as Map?)?.cast<String, dynamic>() ?? const {};
    for (final field in fields) {
      _syncField(sectionKey, field, '${values[field.key] ?? ''}');
    }
  }

  void _syncField(String sectionKey, _Field field, String value) {
    _syncKey(_keyOf(sectionKey, field.key), value);
  }

  void _syncKey(String key, String value) {
    _initial[key] = value;
    final controller = _controllers[key];
    if (controller == null) {
      _controllers[key] = TextEditingController(text: value);
    } else if (!_dirty.contains(key) && controller.text != value) {
      controller.text = value;
    }
  }

  String _text(String key) => _controllers[key]?.text ?? '';

  String _keyOf(String section, String field) => '$section.$field';

  void _dropBank(String sectionId) {
    _banks.remove(sectionId);
    _bankOrder.remove(sectionId);
    _removedBanks.remove(sectionId);
    _expandedBanks.remove(sectionId);
    final doomed = _controllers.keys
        .where((key) => key.startsWith('$sectionId.'))
        .toList();
    for (final key in doomed) {
      _controllers.remove(key)?.dispose();
      _initial.remove(key);
      _dirty.remove(key);
    }
  }

  String _newBankId() {
    var stamp = DateTime.now().millisecondsSinceEpoch;
    String id;
    do {
      id = '${_bankSectionPrefix}b$stamp';
      stamp += 1;
    } while (_banks.containsKey(id));
    return id;
  }

  void _addBank() {
    final id = _newBankId();
    _banks[id] = _BankMeta(id, localOnly: true);
    _bankOrder.add(id);
    _expandedBanks.add(id);
    _setBankValue(id, 'enabled', 'true');
    _setBankValue(id, 'priority', '${_bankOrder.length - 1}');
    _setBankValue(id, 'name', '答题源 ${_bankOrder.length}');
    _setBankValue(id, 'provider', 'TikuYanxi');
    setState(() {});
  }

  /// 新增/重排时直接写入控制器并标记脏（值必然与远端不同）。
  void _setBankValue(String sectionId, String field, String value) {
    final key = _keyOf(sectionId, field);
    _controllers.putIfAbsent(key, () => TextEditingController()).text = value;
    _initial[key] ??= '';
    _dirty.add(key);
  }

  /// 拖拽排序后重写 priority 0..n-1（顺序即回退梯度）。
  /// [preAdjusted] 为 true 时 newIndex 已按“移除后插入”语义调整过
  /// （onReorderItem 回调的约定），不再做 -1 修正。
  void _reorderBanks(int oldIndex, int newIndex, {bool preAdjusted = false}) {
    if (!preAdjusted && newIndex > oldIndex) newIndex -= 1;
    if (oldIndex < 0 ||
        oldIndex >= _bankOrder.length ||
        newIndex < 0 ||
        newIndex >= _bankOrder.length) {
      return;
    }
    final id = _bankOrder.removeAt(oldIndex);
    _bankOrder.insert(newIndex, id);
    for (var i = 0; i < _bankOrder.length; i++) {
      _setBankValue(_bankOrder[i], 'priority', '$i');
    }
    setState(() {});
  }

  /// 仅供测试：绕过手势竞技场直接触发拖拽排序回调
  /// （ReorderableDragStartListener 在嵌套可滚动容器的组件测试里不可靠）。
  @visibleForTesting
  void testReorderBanks(int oldIndex, int newIndex) =>
      _reorderBanks(oldIndex, newIndex, preAdjusted: true);

  void _deleteBank(String sectionId) {
    final meta = _banks[sectionId];
    if (meta != null && !meta.localOnly) {
      _removedBanks.add(sectionId);
    }
    _dropBank(sectionId);
    for (var i = 0; i < _bankOrder.length; i++) {
      _setBankValue(_bankOrder[i], 'priority', '$i');
    }
    setState(() {});
  }

  // ------------------------------------------------------------- 编辑动作

  void _markDirty(String key, String value, {bool silent = false}) {
    _controllers.putIfAbsent(key, () => TextEditingController()).text = value;
    if (value != (_initial[key] ?? '')) {
      _dirty.add(key);
    } else {
      _dirty.remove(key);
    }
    if (!silent) setState(() {});
  }

  // ------------------------------------------------------------- 保存 / 测试

  Map<String, String>? _clientValidate() {
    final specs = <(String, List<_Field>)>[
      for (final section in _fixedSections) (section.sectionKey, section.fields),
      (_tikuGlobalSection.sectionKey, _tikuGlobalSection.fields),
      for (final id in _bankOrder) ...[
        (id, _bankBaseFields),
        (id, _providerFieldsFor(_text(_keyOf(id, 'provider')))),
      ],
    ];
    for (final (sectionKey, fields) in specs) {
      for (final field in fields) {
        final range = field.numeric;
        if (range == null) continue;
        final key = _keyOf(sectionKey, field.key);
        final text = _controllers[key]?.text.trim() ?? '';
        if (text.isEmpty) continue;
        final value = range.isInt ? int.tryParse(text) : double.tryParse(text);
        if (value == null || value < range.min || value > range.max) {
          return {
            'key': key,
            'message':
                '${field.label} 需为${range.isInt ? '整数' : '数字'}（${range.hint}）',
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
    for (final key in _dirty) {
      // 按最后一个点切分：题库实例段名自带点（tiku_bank.<id>.<key>）。
      final dot = key.lastIndexOf('.');
      if (dot <= 0) continue;
      final section = key.substring(0, dot);
      final field = key.substring(dot + 1);
      patch.putIfAbsent(section, () => {})[field] = _controllers[key]?.text ?? '';
    }
    final removed = List.of(_removedBanks);
    try {
      if (patch.isNotEmpty) {
        await ref.read(configProvider.notifier).save(patch);
      }
      if (removed.isNotEmpty) {
        await ref
            .read(engineClientProvider)
            .rpc('config.remove', {'sections': removed});
      }
      _dirty.clear();
      _removedBanks.clear();
      if (!mounted) return;
      // 保存后由 configProvider 回读新值，形成双向同步闭环。
      ref.invalidate(configProvider);
      await ref.read(configProvider.future);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('已保存${removed.isEmpty ? '' : '（含 ${removed.length} 个已删除的答题源）'}')),
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
          SnackBar(
            content: Text(ok ? '测试通过：$message' : '测试未通过：$message'),
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } on EngineException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  // ------------------------------------------------------------------ UI

  @override
  Widget build(BuildContext context) {
    final configAsync = ref.watch(configProvider);
    final theme = Theme.of(context);

    return Column(
      children: [
        Expanded(
          child: Stack(
            children: [
              ListView(
                padding: const EdgeInsets.fromLTRB(24, 24, 24, 8),
                children: [
                  _IntroCard(
                    dark: _dark,
                    onDarkChanged: (value) {
                      setState(() => _dark = value);
                      ref.read(themeModeProvider.notifier).set(
                            value ? ThemeMode.dark : ThemeMode.system,
                          );
                    },
                  ),
                  for (final section in _fixedSections) ...[
                    const SizedBox(height: 16),
                    _SectionCard(
                      title: section.title,
                      intro: section.intro,
                      dirty: _dirty
                          .any((key) => key.startsWith('${section.sectionKey}.')),
                      children: [
                        for (final field in section.fields)
                          _buildField(context, section.sectionKey, field),
                      ],
                    ),
                  ],
                  const SizedBox(height: 16),
                  _buildBanksWorkbench(context),
                  const SizedBox(height: 16),
                  _SectionCard(
                    title: _tikuGlobalSection.title,
                    intro: _tikuGlobalSection.intro,
                    dirty: _dirty.any(
                        (key) => key.startsWith('${_tikuGlobalSection.sectionKey}.')),
                    children: [
                      for (final field in _tikuGlobalSection.fields)
                        _buildField(context, _tikuGlobalSection.sectionKey, field),
                    ],
                  ),
                  const SizedBox(height: 16),
                  _buildNotificationCard(context),
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
            color: theme.colorScheme.surfaceContainerLow,
            border: Border(
                top: BorderSide(color: theme.dividerTheme.color ?? Colors.grey)),
          ),
          child: Row(
            children: [
              FilledButton.icon(
                onPressed: _saving ? null : _save,
                icon: _saving
                    ? const SizedBox(width: 16, height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.save_outlined),
                label: Text(_hasChanges
                    ? '保存配置（${_dirty.length + _removedBanks.length} 项）'
                    : '保存配置'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _saving ? null : () => _test('tiku.test'),
                icon: const Icon(Icons.quiz_outlined),
                label: const Text('测试答题源'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: _saving ? null : () => _test('notification.test'),
                icon: const Icon(Icons.notifications_outlined),
                label: const Text('测试通知'),
              ),
              const Spacer(),
              if (_hasChanges)
                Text('有未保存修改', style: theme.textTheme.bodySmall),
            ],
          ),
        ),
      ],
    );
  }

  // ------------------------------------------------------- 答题源工作台 UI

  Widget _buildBanksWorkbench(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('答题源（梯度回退）', style: theme.textTheme.titleMedium),
                const Spacer(),
                FilledButton.tonalIcon(
                  onPressed: _addBank,
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('添加答题源'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '从上到下依次查询：第 1 个源没查到的题自动问第 2 个，以此类推。'
              '每个源单独配置 token / 模型 / 接口，互不影响；拖动 ⠿ 手柄即可调整梯度顺序。',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline, height: 1.5),
            ),
            const SizedBox(height: 12),
            if (_bankOrder.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  '还没有答题源。点击「添加答题源」创建第一个，'
                  '例如先加「言溪题库」，再加「AI 大模型」作为兜底。',
                  style: theme.textTheme.bodySmall,
                ),
              )
            else
              ReorderableListView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                buildDefaultDragHandles: false,
                padding: EdgeInsets.zero,
                itemCount: _bankOrder.length,
                onReorderItem: (oldIndex, newIndex) =>
                    _reorderBanks(oldIndex, newIndex, preAdjusted: true),
                proxyDecorator: (child, index, animation) => ScaleTransition(
                  scale: Tween<double>(begin: 1, end: 1.02).animate(animation),
                  child: child,
                ),
                itemBuilder: (context, index) => Container(
                  key: ValueKey(_bankOrder[index]),
                  margin: const EdgeInsets.only(bottom: 12),
                  child: _buildBankCard(context, index),
                ),
              ),
          ],
        ),
      ),
    );
  }

  bool _bankDirty(String id) => _dirty.any((key) => key.startsWith('$id.'));

  Widget _buildBankCard(BuildContext context, int index) {
    final sectionId = _bankOrder[index];
    final provider = _text(_keyOf(sectionId, 'provider'));
    final meta = _bankProviders[provider];
    final enabled =
        _text(_keyOf(sectionId, 'enabled')).trim().toLowerCase() != 'false';
    final name = _text(_keyOf(sectionId, 'name')).trim();
    final providerFields = _providerFieldsFor(provider);
    final theme = Theme.of(context);
    final expanded = _expandedBanks.contains(sectionId);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerLow.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: _bankDirty(sectionId)
              ? theme.colorScheme.primary.withValues(alpha: 0.5)
              : theme.dividerTheme.color ?? Colors.grey.withValues(alpha: 0.3),
        ),
      ),
      // 卡片自带背景色，内部开关需要自己的 Material 才能正确绘制水波纹。
      child: Material(
        type: MaterialType.transparency,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                // 序号即回退优先级：1 = 最先查询
                Container(
                  width: 26,
                  height: 26,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: enabled
                        ? theme.colorScheme.primaryContainer
                        : theme.colorScheme.surfaceContainerHighest,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    '${index + 1}',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: enabled
                          ? theme.colorScheme.onPrimaryContainer
                          : theme.colorScheme.outline,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: InkWell(
                    onTap: () => setState(() {
                      if (expanded) {
                        _expandedBanks.remove(sectionId);
                      } else {
                        _expandedBanks.add(sectionId);
                      }
                    }),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name.isEmpty ? sectionId : name,
                          style: theme.textTheme.titleSmall,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        Text(
                          meta == null
                              ? (provider.isEmpty ? '未选择答题源类型' : provider)
                              : (expanded ? meta.desc : '${meta.display} · 点按展开配置'),
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: theme.colorScheme.outline),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                ),
                // 拖拽手柄：按住即可调整梯度顺序
                ReorderableDragStartListener(
                  index: index,
                  child: Padding(
                    padding: const EdgeInsets.all(8),
                    child: Icon(Icons.drag_handle,
                        size: 20, color: theme.colorScheme.outline),
                  ),
                ),
                Switch(
                  value: enabled,
                  onChanged: (next) =>
                      _markDirty(_keyOf(sectionId, 'enabled'), '$next'),
                ),
                IconButton(
                  tooltip: expanded ? '收起配置' : '展开配置',
                  onPressed: () => setState(() {
                    if (expanded) {
                      _expandedBanks.remove(sectionId);
                    } else {
                      _expandedBanks.add(sectionId);
                    }
                  }),
                  icon: AnimatedRotation(
                    turns: expanded ? 0.5 : 0,
                    duration: const Duration(milliseconds: 180),
                    child: const Icon(Icons.expand_more, size: 20),
                  ),
                ),
                IconButton(
                  tooltip: '删除该答题源',
                  onPressed: () => _deleteBank(sectionId),
                  icon: Icon(Icons.delete_outline,
                      size: 18, color: theme.colorScheme.error),
                ),
              ],
            ),
            // AnimatedSwitcher 而非 AnimatedCrossFade：收起态不常驻挂载配置区，
            // 避免隐藏的 TextField 仍留在树里（也省掉大段 JSON 配置的隐藏构建开销）。
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 180),
              switchInCurve: Curves.easeOutCubic,
              transitionBuilder: (child, animation) =>
                  SizeTransition(sizeFactor: animation, child: child),
              child: expanded
                  ? KeyedSubtree(
                      key: ValueKey('expanded-$sectionId'),
                      child: Padding(
                        padding: const EdgeInsets.only(top: 10),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (!enabled)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 6),
                                child: Text('已停用：该源不参与查询，配置保留。',
                                    style: theme.textTheme.bodySmall
                                        ?.copyWith(color: theme.colorScheme.outline)),
                              ),
                            DropdownButtonFormField<String>(
                              initialValue:
                                  _bankProviders.containsKey(provider) ? provider : null,
                              decoration: const InputDecoration(
                                labelText: '答题源类型',
                                helperText: '切换类型后仅显示该类型的配置项',
                              ),
                              items: [
                                for (final entry in _bankProviders.entries)
                                  DropdownMenuItem(
                                    value: entry.key,
                                    child: Text('${entry.value.display}（${entry.key}）'),
                                  ),
                              ],
                              onChanged: (value) {
                                if (value == null || value == provider) return;
                                _markDirty(_keyOf(sectionId, 'provider'), value);
                              },
                            ),
                            const SizedBox(height: 4),
                            _buildField(
                              context,
                              sectionId,
                              const _Field('name', '实例名称',
                                  helper: '仅用于在本页展示，方便区分多个实例'),
                            ),
                            for (final field in providerFields)
                              _buildField(context, sectionId, field),
                            if (providerFields.isEmpty)
                              Padding(
                                padding: const EdgeInsets.symmetric(vertical: 6),
                                child: Text('该类型暂无额外配置。',
                                    style: theme.textTheme.bodySmall
                                        ?.copyWith(color: theme.colorScheme.outline)),
                              ),
                          ],
                        ),
                      ),
                    )
                  : const SizedBox(width: double.infinity, key: ValueKey('collapsed')),
            ),
          ],
        ),
      ),
    );
  }

  // ----------------------------------------------------------- 通知源 UI

  Widget _buildNotificationCard(BuildContext context) {
    final provider = _text('notification.provider');
    final knownProvider = _notificationProviderMeta.containsKey(provider);
    final theme = Theme.of(context);
    return _SectionCard(
      title: _notificationSection.title,
      intro: _notificationSection.intro,
      dirty: _dirty.any((key) => key.startsWith('notification.')),
      children: [
        DropdownButtonFormField<String>(
          initialValue: knownProvider ? provider : null,
          decoration: InputDecoration(
            labelText: '通知服务',
            helperText: provider.isEmpty
                ? '留空则不启用通知'
                : (_notificationProviderMeta[provider] ?? '自定义 provider'),
          ),
          items: [
            for (final option in _notificationProviderMeta.keys)
              DropdownMenuItem(value: option, child: Text(option)),
          ],
          onChanged: (value) =>
              _markDirty('notification.provider', value ?? ''),
        ),
        if (provider.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text('选择一个通知服务后，这里只显示它需要的配置项。',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline)),
          )
        else ...[
          _buildField(context, 'notification', _notificationSection.fields[1]),
          if (provider == 'Telegram')
            _buildField(context, 'notification', _notificationSection.fields[2]),
        ],
      ],
    );
  }

  // ------------------------------------------------------------- 字段渲染

  Widget _buildField(BuildContext context, String sectionKey, _Field field) {
    final key = _keyOf(sectionKey, field.key);
    final controller = _controllers.putIfAbsent(key, () => TextEditingController());

    if (field.boolField) {
      final value = controller.text.trim().toLowerCase() == 'true';
      return SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(field.label),
        subtitle: field.helper == null ? null : Text(field.helper!),
        value: value,
        onChanged: (next) => _markDirty(key, '$next'),
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
        minLines: field.multiline ? 5 : 1,
        maxLines: field.multiline ? 10 : 1,
        keyboardType:
            field.multiline ? TextInputType.multiline : TextInputType.text,
        onChanged: (value) => _markDirty(key, value),
        decoration: InputDecoration(
          labelText: field.label,
          helperText: field.helper,
          helperMaxLines: 4,
          alignLabelWithHint: field.multiline,
        ),
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.title,
    required this.children,
    this.intro,
    this.dirty = false,
  });

  final String title;
  final String? intro;
  final List<Widget> children;
  final bool dirty;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(title, style: theme.textTheme.titleMedium),
                const Spacer(),
                if (dirty)
                  Tooltip(
                    message: '有未保存修改',
                    child: Icon(Icons.circle, size: 8,
                        color: theme.colorScheme.primary),
                  ),
              ],
            ),
            if (intro != null) ...[
              const SizedBox(height: 6),
              Text(intro!,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline, height: 1.5)),
            ],
            const SizedBox(height: 12),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// 页首说明卡：这个设置页怎么用，给第一次接触的小白。
class _IntroCard extends StatelessWidget {
  const _IntroCard({required this.dark, required this.onDarkChanged});

  final bool dark;
  final ValueChanged<bool> onDarkChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('设置工作台', style: theme.textTheme.titleMedium),
                const Spacer(),
                const Text('深色主题'),
                const SizedBox(width: 4),
                Switch(
                  value: dark,
                  onChanged: onDarkChanged,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '按顺序配置：① 账号 → ② 学习策略 → ③ 至少一个答题源 → ④ 通知（可选）。'
              '每项旁边都有说明；改完点底部「保存配置」，再用「测试答题源」验证是否可用。'
              '配置保存在引擎的 config.ini，与日志、cookies 同目录。',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline, height: 1.6),
            ),
          ],
        ),
      ),
    );
  }
}
