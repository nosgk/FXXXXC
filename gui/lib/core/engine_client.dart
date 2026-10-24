import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

class EngineException implements Exception {
  EngineException(this.code, this.message);

  final int code;
  final String message;

  @override
  String toString() => 'EngineException($code): $message';
}

/// Owns the Python engine process and the HTTP/WebSocket connection to it.
class EngineClient {
  EngineClient();

  Process? _process;
  WebSocketChannel? _channel;
  http.Client? _http;
  int? _port;
  String _token = '';
  Directory? _dataDir;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _ready = Completer<int>();
  bool _starting = false;
  Timer? _reconnectTimer;

  Stream<Map<String, dynamic>> get events => _events.stream;
  bool get isRunning => _process != null;
  int? get port => _port;
  String get dataDirPath => _dataDir?.path ?? '';

  Directory _resolveDataDir() {
    final base = Platform.environment['APPDATA'] ?? Directory.systemTemp.path;
    return Directory('$base${Platform.pathSeparator}FXXXXC');
  }

  String _bundledEnginePath() {
    final exe = Platform.resolvedExecutable;
    final dir = File(exe).parent.path;
    return '$dir${Platform.pathSeparator}engine'
        '${Platform.pathSeparator}fxxxxc-engine.exe';
  }

  Future<void> start() async {
    if (_process != null || _starting) return;
    _starting = true;
    try {
      _token = _randomToken();
      _dataDir = _resolveDataDir();
      await _dataDir!.create(recursive: true);
      _http = http.Client();

      final bundled = File(_bundledEnginePath());
      Process process;
      if (bundled.existsSync()) {
        process = await Process.start(
          bundled.path,
          ['--port', '0', '--data-dir', _dataDir!.path],
          // Keep the parent environment (SystemRoot etc.) or TLS/network init
          // inside the engine breaks on Windows.
          environment: {...Platform.environment, 'FXXXXC_ENGINE_TOKEN': _token},
          workingDirectory: _dataDir!.path,
        );
      } else {
        // Development fallback: run from the repository root.
        final repoRoot = Directory.current.parent.path;
        process = await Process.start(
          'python',
          ['-m', 'fxxxxc.engine', '--port', '0', '--data-dir', _dataDir!.path],
          environment: {...Platform.environment, 'FXXXXC_ENGINE_TOKEN': _token},
          workingDirectory: repoRoot,
          runInShell: true,
        );
      }
      _process = process;

      process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) => _handleEngineLine(line));
      process.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) => debugPrint('[engine] $line'));

      process.exitCode.then((code) {
        debugPrint('[engine] exited with $code');
        _process = null;
        _channel?.sink.close();
        _channel = null;
        if (!_ready.isCompleted) {
          _ready.completeError(EngineException(-1, '引擎进程已退出 (code=$code)'));
        }
      });

      _port = await _ready.future.timeout(const Duration(seconds: 20));
      await _connectWebSocket();
    } finally {
      _starting = false;
    }
  }

  void _handleEngineLine(String line) {
    if (line.trim().isEmpty) return;
    try {
      final payload = jsonDecode(line);
      if (payload is Map && payload['status'] == 'ready') {
        final port = (payload['port'] as num).toInt();
        if (!_ready.isCompleted) _ready.complete(port);
      }
    } on FormatException {
      debugPrint('[engine] $line');
    }
  }

  Future<void> _connectWebSocket() async {
    final port = _port;
    if (port == null) return;
    _channel?.sink.close();
    _channel = WebSocketChannel.connect(
      Uri.parse('ws://127.0.0.1:$port/events'),
    );
    _channel!.stream.listen(
      (data) {
        if (data is! String) return;
        try {
          final payload = jsonDecode(data);
          if (payload is Map && payload['method'] == 'event') {
            final params = payload['params'];
            if (params is Map<String, dynamic>) {
              _events.add(params);
            }
          }
        } on FormatException {
          // ignore malformed frames
        }
      },
      onDone: () {
        _reconnectTimer?.cancel();
        _reconnectTimer = Timer(const Duration(seconds: 2), () {
          if (_process != null) _connectWebSocket();
        });
      },
      onError: (Object error) => debugPrint('[ws] $error'),
    );
  }

  String _randomToken() {
    final random = Random.secure();
    return base64UrlEncode(
      List<int>.generate(32, (_) => random.nextInt(256)),
    ).replaceAll('=', '');
  }

  Map<String, String> _headers() => {
        'Authorization': 'Bearer $_token',
        'Content-Type': 'application/json',
      };

  Uri _rpcUri() => Uri.parse('http://127.0.0.1:$_port/rpc');

  Future<dynamic> rpc(String method, [Map<String, dynamic> params = const {}]) async {
    final client = _http ??= http.Client();
    final response = await client.post(
      _rpcUri(),
      headers: _headers(),
      body: jsonEncode({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}),
    );
    if (response.statusCode == 401) {
      throw EngineException(401, '引擎鉴权失败');
    }
    final body = jsonDecode(response.body);
    if (body is Map && body['error'] is Map) {
      final error = body['error'] as Map;
      throw EngineException(
        (error['code'] as num?)?.toInt() ?? -32000,
        '${error['message'] ?? '未知错误'}',
      );
    }
    return body is Map ? body['result'] : null;
  }

  Future<void> stop() async {
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    _channel = null;
    _http?.close();
    _http = null;
    final process = _process;
    _process = null;
    if (process != null) {
      process.kill();
      await process.exitCode.timeout(const Duration(seconds: 3), onTimeout: () => 0);
    }
  }
}
