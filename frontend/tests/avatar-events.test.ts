import test from 'node:test';
import assert from 'node:assert/strict';
import { createAvatarCursor, observeAvatarStages, type ObservedStage } from '../lib/avatar-events.ts';
const stage = (id: string, sequence: number, status: ObservedStage['status'] = 'active'): ObservedStage => ({ id, accepted_sequence: sequence, status });

test('hydration and refresh never replay old entries or losses', () => {
  const cursor = createAvatarCursor(), history = [stage('old-open', 5), stage('old-loss', 6, 'exploded')];
  assert.equal(observeAvatarStages(cursor, history, 10), null);
  assert.equal(observeAvatarStages(cursor, history, 20), null);
  assert.equal(observeAvatarStages(cursor, [stage('older-history', 2, 'exploded'), ...history], 30), null);
});

test('accepted receipts trigger once, including concurrent responses received out of order', () => {
  const cursor = createAvatarCursor(); observeAvatarStages(cursor, [], 0);
  for (const [id, seq] of [['BTC', 3], ['HYPE', 1], ['ETH', 2]] as const) {
    assert.equal(observeAvatarStages(cursor, [stage(id, seq)], 10, true)?.kind, 'entry');
    assert.equal(observeAvatarStages(cursor, [stage(id, seq)], 20, true), null);
  }
  assert.equal(observeAvatarStages(cursor, [stage('BTC', 3), stage('HYPE', 1), stage('ETH', 2)], 30), null);
});

test('polling detects fresh entry and exactly one confirmed loss, without reacting to pending', () => {
  const cursor = createAvatarCursor(); observeAvatarStages(cursor, [], 0);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1)], 10)?.kind, 'entry');
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'pending')], 20), null);
  assert.deepEqual(observeAvatarStages(cursor, [stage('a', 1, 'exploded')], 30), { id: 'a:loss', kind: 'loss', at: 30 });
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'exploded')], 40), null);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1)], 50), null);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'exploded')], 60), null);
});

test('first snapshot can resolve a known receipt without replaying unrelated history', () => {
  const cursor = createAvatarCursor();
  assert.equal(observeAvatarStages(cursor, [stage('new', 5)], 1, true)?.kind, 'entry');
  assert.equal(observeAvatarStages(cursor, [stage('old', 2, 'exploded'), stage('new', 5, 'exploded')], 2)?.id, 'new:loss');
});

test('confirmed wins cheer once, refunds stay silent, and a fast breach still reacts', () => {
  const cursor = createAvatarCursor(); observeAvatarStages(cursor, [stage('a', 1), stage('b', 2)], 0);
  assert.deepEqual(observeAvatarStages(cursor, [stage('a', 1, 'survived'), stage('b', 2, 'voided')], 1), { id: 'a:win', kind: 'win', at: 1 });
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'survived'), stage('b', 2, 'voided')], 2), null);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1)], 3), null);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'survived')], 4), null);
  assert.equal(observeAvatarStages(cursor, [stage('fast', 3, 'exploded')], 2)?.kind, 'loss');
});

test('hydrated winning history is silent and a fresh win beats an entry in the same snapshot', () => {
  const cursor = createAvatarCursor();
  assert.equal(observeAvatarStages(cursor, [stage('history', 1, 'survived'), stage('open', 2)], 0), null);
  assert.equal(observeAvatarStages(cursor, [stage('next', 3), stage('open', 2, 'survived')], 1)?.kind, 'win');
});

test('a loss takes priority over a simultaneous entry and a new account starts a silent baseline', () => {
  const cursor = createAvatarCursor(); observeAvatarStages(cursor, [stage('a', 1)], 0);
  assert.equal(observeAvatarStages(cursor, [stage('a', 1, 'exploded'), stage('b', 2)], 1)?.kind, 'loss');
  assert.equal(observeAvatarStages(createAvatarCursor(), [stage('b', 2), stage('a', 1, 'exploded')], 2), null);
});
