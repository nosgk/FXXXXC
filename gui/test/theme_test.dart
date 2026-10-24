import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:fxxxxc/theme.dart';

void main() {
  test('light and dark themes are Material 3 with the seed color', () {
    final light = buildFxxxxcTheme(Brightness.light, kSeedColor);
    final dark = buildFxxxxcTheme(Brightness.dark, kSeedColor);

    expect(light.useMaterial3, isTrue);
    expect(dark.useMaterial3, isTrue);
    expect(light.colorScheme.primary, isNot(dark.colorScheme.primary));
    expect(light.cardTheme.elevation, 0);
  });
}
