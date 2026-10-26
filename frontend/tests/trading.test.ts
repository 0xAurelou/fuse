import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { ASSETS, PAYOUT_OPTIONS, MARKET_FIXTURES, demoObservations, EngineError, engineRequest, formatUsdc, payoutTerms, previewCorridor, validMultiplier, brownianWidthPPB } from '../lib/trading.ts';

test('the nine payout presets include the original stake and preserve atomic precision', () => {
  let previousWidth = Infinity;
  assert.deepEqual(PAYOUT_OPTIONS, [2, 5, 10, 25, 50, 100, 250, 1000, 10000]);
  for (const multiplier of PAYOUT_OPTIONS) {
    const terms = payoutTerms('10.123456', multiplier)!;
    assert.equal(terms.payout, 10_123_456n * BigInt(multiplier));
    assert.equal(terms.profit + terms.stake, terms.payout);
    const corridor = previewCorridor(multiplier);
    assert.ok(corridor.widthPPB < previousWidth);
    assert.equal(corridor.upper - corridor.price, corridor.price - corridor.lower);
    previousWidth = corridor.widthPPB;
  }
  assert.equal(formatUsdc(payoutTerms('10', 100)!.payout), '$1,000.00');
  assert.equal(formatUsdc(payoutTerms('10', 10000)!.payout), '$100,000.00');
  assert.equal(formatUsdc(10_123_456n), '$10.123456');
  assert.equal(formatUsdc(1n), '$0.000001');
});

test('out-of-range, fractional and unsafe amounts cannot become quote requests', () => {
  for (const multiplier of [0, 1, 1.99, 2.5, 3, 24, 26, 99, 100.01, 101, 249, 251, 999, 1001, 9999, 10001, Infinity, NaN]) {
    assert.equal(validMultiplier(multiplier), false);
    assert.equal(payoutTerms('10', multiplier), null);
    assert.throws(() => previewCorridor(multiplier));
  }
  assert.equal(payoutTerms('1000000', 10000), null);
  for (const stake of ['0', '-1', '1e4', '10.0000001', '9007199254740993']) assert.equal(payoutTerms(stake, 100), null);
});

test('engine transport keeps selected quote terms and original retry identity', async t => {
  const calls: { url: string; options: RequestInit }[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ result: { id: 'accepted-stage', payout: 1_000_000_000 } }), { status: 200 });
  });
  await engineRequest('quotes', { token: 'test-session', key: 'quote-key', body: { amount: Number(payoutTerms('10', 100)!.stake), multiplier: 100 } });
  for (let retry = 0; retry < 2; retry++) await engineRequest('stages', { token: 'test-session', key: 'original-entry-key', body: { id: 'quote-100x' } });
  assert.deepEqual(JSON.parse(calls[0].options.body as string), { amount: 10_000_000, multiplier: 100 });
  assert.equal(calls[0].url, '/engine/v1/quotes');
  assert.deepEqual(calls[1], calls[2]);
  assert.equal((calls[1].options.headers as Record<string, string>)['Idempotency-Key'], 'original-entry-key');
  assert.equal((calls[1].options.headers as Record<string, string>).Authorization, 'Bearer test-session');
  assert.deepEqual(JSON.parse(calls[1].options.body as string), { id: 'quote-100x' });
});

test('engine rejections preserve their status for definite versus uncertain entry handling', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: 'quote expired' }), { status: 409 }));
  await assert.rejects(engineRequest('stages', { body: { id: 'expired' }, key: 'entry' }), error => error instanceof EngineError && error.status === 409 && error.message === 'quote expired');
});

test('browser and Go barrier widths match the same independent reference vectors', () => {
  const vectors = JSON.parse(readFileSync(new URL('../../engine/testdata/brownian-pricing-vectors.json', import.meta.url), 'utf8')) as { multiplier: number; volatility_30s_ppm: number; house_edge_bps: number; width_ppb: number }[];
  for (const vector of vectors) {
    assert.equal(brownianWidthPPB(vector.multiplier, { rule: 'brownian-first-mode-v1', ...vector }), vector.width_ppb);
  }
});

test('Degen fixtures are deterministic and priced independently for BTC, HYPE and ETH', () => {
  for (const asset of ASSETS) {
    const values = demoObservations(asset, 12345);
    assert.deepEqual(values, demoObservations(asset, 12345));
    assert.equal(values.length, 64);
    assert.ok(values.every(Number.isSafeInteger));
    assert.ok(values.every(value => value > 0));
    const model = { rule: 'brownian-first-mode-v1', volatility_30s_ppm: MARKET_FIXTURES[asset].volatility, house_edge_bps: 500 };
    const terms = previewCorridor(25, values.at(-1)!, model);
    assert.ok(terms.lower < terms.price && terms.price < terms.upper);
  }
  assert.notDeepEqual(demoObservations('BTC', 12345), demoObservations('ETH', 12345));
});
