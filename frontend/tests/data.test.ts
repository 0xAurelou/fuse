import assert from 'node:assert/strict';
import test from 'node:test';
import { datasets, exportRows, parseUsdc, periods, SNAPSHOT, snapshotCsv } from '../lib/demo.ts';

test('every filtered CSV matches the displayed snapshot and metric values', () => {
  for (const period of periods) {
    const rows = exportRows(period);
    const csv = snapshotCsv(period).split('\n');
    assert.equal(csv.length, Object.keys(datasets[period]).length + 1);
    for (const row of rows) {
      assert.equal(row.snapshot, SNAPSHOT.id);
      assert.equal(row.grade, 'DEMO DATA');
      assert.equal(row.period, period);
      assert.equal(row.value, datasets[period][row.metric as keyof typeof datasets['24H']]);
      assert.ok(csv.includes(Object.values(row).join(',')));
    }
  }
});

test('USDC input keeps atomic precision and rejects malformed or nonpositive amounts', () => {
  assert.equal(parseUsdc('0.000001'), 1n);
  assert.equal(parseUsdc('10.123456'), 10_123_456n);
  assert.equal(parseUsdc('9007199254740993.000001'), 9_007_199_254_740_993_000_001n);
  for (const invalid of ['', '-10', '0', '0.000000', '1.0000001', '1e4', 'NaN', '1,000', ' 1', '1.2.3']) {
    assert.equal(parseUsdc(invalid), null, invalid);
  }
});

test('fixtures maintain the displayed solvency equation and count every independent stake once', () => {
  for (const data of Object.values(datasets)) {
    assert.ok(data.required > 0 && data.equity > data.required);
    assert.equal((data.equity / data.required).toFixed(2), '2.67');
    assert.equal(data.initialRisk, data.turnover);
  }
});
