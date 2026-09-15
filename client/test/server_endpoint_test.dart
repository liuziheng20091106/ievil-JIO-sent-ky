import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/models.dart';

void main() {
  test('accepts only safe service roots', () {
    expect(ServerEndpoint.parse('http://127.0.0.1:8000').liveUri.toString(), 'ws://127.0.0.1:8000/api/live');
    expect(ServerEndpoint.parse('http://192.168.1.4').api('/api/me').toString(), 'http://192.168.1.4/api/me');
    expect(ServerEndpoint.parse('https://game.example.com/').toString(), 'https://game.example.com');

    expect(() => ServerEndpoint.parse('http://game.example.com'), throwsFormatException);
    expect(() => ServerEndpoint.parse('https://game.example.com/api'), throwsFormatException);
    expect(() => ServerEndpoint.parse('https://game.example.com?token=x'), throwsFormatException);
    expect(() => ServerEndpoint.parse('ftp://127.0.0.1'), throwsFormatException);
  });
}
