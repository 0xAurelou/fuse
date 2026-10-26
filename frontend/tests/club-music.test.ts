import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_TRACK_ID, isYouTubeVideoId, parseYouTubeVideoId } from '../lib/club-music.ts';

test('music accepts common YouTube video links and ignores sharing or playlist parameters', () => {
  for (const link of [
    `https://www.youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    ` http://youtube.com/watch?list=PL123&v=${DEFAULT_TRACK_ID}&t=42 `,
    `https://youtu.be/${DEFAULT_TRACK_ID}?si=share-token`,
    `youtu.be/${DEFAULT_TRACK_ID}`,
    `www.youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    `https://m.youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    `https://music.youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    `https://www.youtube.com/shorts/${DEFAULT_TRACK_ID}`,
    `https://www.youtube.com/live/${DEFAULT_TRACK_ID}`,
    `https://www.youtube.com/embed/${DEFAULT_TRACK_ID}`,
  ]) assert.equal(parseYouTubeVideoId(link), DEFAULT_TRACK_ID, link);
});

test('music rejects non-video links, invalid IDs, unsafe protocols, and lookalike hosts', () => {
  for (const link of [
    '', DEFAULT_TRACK_ID, 'not a url',
    'https://youtube.com/playlist?list=PL123',
    'https://youtube.com/watch?v=short',
    'https://youtube.com/watch?v=0123456789!qt',
    `https://youtu.be/${DEFAULT_TRACK_ID}/extra`,
    `https://youtube.com.evil.test/watch?v=${DEFAULT_TRACK_ID}`,
    `https://evilyoutube.com/watch?v=${DEFAULT_TRACK_ID}`,
    `https://youtube.com@evil.test/watch?v=${DEFAULT_TRACK_ID}`,
    `https://user@youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    `https://youtube.com:444/watch?v=${DEFAULT_TRACK_ID}`,
    `ftp://youtube.com/watch?v=${DEFAULT_TRACK_ID}`,
    'javascript:alert(1)',
  ]) assert.equal(parseYouTubeVideoId(link), null, link);
});

test('stored music IDs are validated before reaching the player', () => {
  assert.equal(isYouTubeVideoId(DEFAULT_TRACK_ID), true);
  assert.equal(isYouTubeVideoId('AbC0123_-xy'), true);
  for (const value of ['', 'null', '{}', 'bad', '0123456789abc', '<script>']) {
    assert.equal(isYouTubeVideoId(value), false, value);
  }
});
