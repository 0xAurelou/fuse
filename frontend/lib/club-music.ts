export const DEFAULT_TRACK_ID = '-_LehYlxcrU';
export const MUSIC_STORAGE_KEY = 'fuse:degen-music:v1';

export function isYouTubeVideoId(value: string): boolean {
  return /^[a-zA-Z0-9_-]{11}$/.test(value);
}

export function parseYouTubeVideoId(input: string): string | null {
  try {
    const value = input.trim();
    const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null;
    const host = url.hostname;
    const path = url.pathname.split('/').filter(Boolean);
    let id: string | null = null;
    if (host === 'youtu.be' && path.length === 1) id = path[0];
    else if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'].includes(host)) {
      if (url.pathname === '/watch') id = url.searchParams.get('v');
      else if (path.length === 2 && ['shorts', 'live', 'embed'].includes(path[0])) id = path[1];
    }
    return id && isYouTubeVideoId(id) ? id : null;
  } catch {
    return null;
  }
}
