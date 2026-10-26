'use client';

import Script from 'next/script';
import { RaveLasers } from './rave-lasers';
import { useEffect, useId, useRef, useState } from 'react';
import { DEFAULT_TRACK_ID, MUSIC_STORAGE_KEY, isYouTubeVideoId, parseYouTubeVideoId } from '../lib/club-music';

type Player = {
  playVideo: () => void;
  pauseVideo: () => void;
  unMute: () => void;
  setVolume: (volume: number) => void;
  destroy: () => void;
  getIframe: () => HTMLIFrameElement;
};
type PlayerEvent = { target: Player };
type YouTubeWindow = Window & {
  onYouTubeIframeAPIReady?: () => void;
  YT?: {
    Player: new (element: HTMLElement, options: {
      width: number;
      height: number;
      videoId: string;
      playerVars: Record<string, string | number>;
      events: {
        onReady: (event: PlayerEvent) => void;
        onStateChange: (event: PlayerEvent & { data: number }) => void;
        onAutoplayBlocked: () => void;
        onError: () => void;
      };
    }) => Player;
  };
};
type Status = 'loading' | 'playing' | 'paused' | 'blocked' | 'error';

export function ClubMusic({ playing }: { playing: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<Player | null>(null);
  const ready = useRef(false);
  const desiredPlaying = useRef(playing);
  const [apiReady, setApiReady] = useState(false);
  const [status, setStatus] = useState<Status>('loading');
  const [trackId, setTrackId] = useState(DEFAULT_TRACK_ID);
  const [preferenceReady, setPreferenceReady] = useState(false);
  const [editing, setEditing] = useState(false);
  const [link, setLink] = useState('');
  const [inputError, setInputError] = useState('');
  const [storageUnavailable, setStorageUnavailable] = useState(false);
  const changeButton = useRef<HTMLButtonElement>(null);
  const editorId = useId();
  const customTrack = trackId !== DEFAULT_TRACK_ID;
  const trackUrl = `https://www.youtube.com/watch?v=${trackId}`;

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(MUSIC_STORAGE_KEY);
      if (saved && isYouTubeVideoId(saved)) setTrackId(saved);
    } catch {
      setStorageUnavailable(true);
    }
    // Restore the selection before creating a player, so the default never plays first.
    setPreferenceReady(true);
  }, []);

  useEffect(() => {
    desiredPlaying.current = playing;
    if (!ready.current) return;
    if (playing) player.current?.playVideo();
    else player.current?.pauseVideo();
  }, [playing]);

  useEffect(() => {
    const youtube = window as YouTubeWindow;
    const previous = youtube.onYouTubeIframeAPIReady;
    const onReady = () => { previous?.(); setApiReady(true); };
    youtube.onYouTubeIframeAPIReady = onReady;
    if (youtube.YT?.Player) setApiReady(true);
    return () => {
      if (youtube.onYouTubeIframeAPIReady === onReady) youtube.onYouTubeIframeAPIReady = previous;
    };
  }, []);

  useEffect(() => {
    const youtube = window as YouTubeWindow;
    const container = host.current;
    if (!preferenceReady || !apiReady || !youtube.YT || !container) return;
    setStatus('loading');
    // YouTube replaces its mount node; keep that node outside React's children.
    const mount = document.createElement('div');
    container.appendChild(mount);
    let disposed = false;
    const instance = new youtube.YT.Player(mount, {
      width: 240,
      height: 200,
      videoId: trackId,
      playerVars: { autoplay: 0, playsinline: 1, loop: 1, playlist: trackId, origin: window.location.origin, rel: 0 },
      events: {
        onReady: ({ target }) => {
          if (disposed) return;
          ready.current = true;
          target.getIframe().title = 'After Hours DJ music — YouTube player';
          target.unMute();
          target.setVolume(40);
          if (desiredPlaying.current) target.playVideo();
          else { target.pauseVideo(); setStatus('paused'); }
        },
        onStateChange: ({ target, data }) => {
          if (disposed) return;
          if (data === 1 && !desiredPlaying.current) { target.pauseVideo(); return; }
          if (data === 1) setStatus('playing');
          else if (data === 2 || data === 0) setStatus('paused');
        },
        onAutoplayBlocked: () => { if (!disposed) setStatus('blocked'); },
        onError: () => { if (!disposed) setStatus('error'); },
      },
    });
    player.current = instance;
    return () => {
      disposed = true;
      ready.current = false;
      player.current = null;
      instance.destroy();
      container.replaceChildren();
    };
  }, [apiReady, preferenceReady, trackId]);

  useEffect(() => {
    if (!preferenceReady || !playing || status !== 'loading') return;
    const timeout = window.setTimeout(() => setStatus('error'), 20_000);
    return () => window.clearTimeout(timeout);
  }, [status, preferenceReady, playing, trackId]);

  function closeEditor() {
    setEditing(false);
    setInputError('');
    changeButton.current?.focus();
  }

  function selectTrack(id: string) {
    setTrackId(id);
    try {
      if (id === DEFAULT_TRACK_ID) window.localStorage.removeItem(MUSIC_STORAGE_KEY);
      else window.localStorage.setItem(MUSIC_STORAGE_KEY, id);
      setStorageUnavailable(false);
    } catch {
      setStorageUnavailable(true);
    }
    closeEditor();
  }

  function startMusic() {
    if (!playing || !ready.current) return;
    player.current?.unMute();
    player.current?.playVideo();
  }

  const message = !playing ? 'Paused with the DJ' : status === 'playing' ? 'Now playing · on repeat' : status === 'blocked' ? 'Tap to start the soundtrack' : status === 'paused' ? 'Soundtrack paused' : status === 'error' ? customTrack ? 'Music unavailable. Try another video or reset to default.' : 'Music unavailable. Try another video or open YouTube.' : 'Loading the soundtrack…';

  return <section className="club-music" aria-label="DJ soundtrack">
    <RaveLasers/>
    <Script src="https://www.youtube.com/iframe_api" strategy="afterInteractive" onReady={() => { if ((window as YouTubeWindow).YT?.Player) setApiReady(true); }} onError={() => setStatus('error')}/>
    <div className="club-music-player" ref={host}/>
    <div className="club-music-info">
      <span className="club-music-label">AFTER HOURS RADIO</span>
      <strong>{customTrack ? 'Your soundtrack' : 'Hyper Vibe · DJ Leaf'}</strong>
      <span>{customTrack ? 'Your degen session. Your soundtrack.' : '200+ BPM Hardcore Mix'}</span>
      <span role="status">{message}</span>
      {playing && (status === 'blocked' || status === 'paused') ? <button className="club-music-start" onClick={startMusic}>▶ Start music</button> : null}
      <a href={trackUrl} target="_blank" rel="noopener noreferrer">Listen on YouTube ↗</a>
      <div className="club-music-actions">
        <button type="button" className="club-music-change" ref={changeButton} aria-expanded={editing} aria-controls={editorId} onClick={() => {
          if (editing) closeEditor();
          else { setLink(customTrack ? trackUrl : ''); setInputError(''); setEditing(true); }
        }}>Change music</button>
        {customTrack ? <button type="button" className="club-music-reset" onClick={() => selectTrack(DEFAULT_TRACK_ID)}>Reset to default</button> : null}
      </div>
      {editing ? <form id={editorId} className="club-music-editor" onSubmit={event => {
        event.preventDefault();
        const id = parseYouTubeVideoId(link);
        if (!id) { setInputError('Paste a YouTube video link, such as youtube.com/watch?v=… or youtu.be/…'); return; }
        selectTrack(id);
      }} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); closeEditor(); } }}>
        <label htmlFor={`${editorId}-link`}>YouTube video link</label>
        <input id={`${editorId}-link`} type="text" inputMode="url" autoFocus autoComplete="off" spellCheck={false} maxLength={2048} value={link} placeholder="https://www.youtube.com/watch?v=…" aria-invalid={Boolean(inputError)} aria-describedby={`${editorId}-hint${inputError ? ` ${editorId}-error` : ''}`} onChange={event => { setLink(event.target.value); setInputError(''); }}/>
        <span id={`${editorId}-hint`}>Choose a video or mix. {storageUnavailable ? 'Device storage is unavailable; changes last for this session.' : 'Your choice is saved on this device.'}</span>
        {inputError ? <span id={`${editorId}-error`} className="club-music-error" role="alert">{inputError}</span> : null}
        <div className="club-music-actions"><button type="submit" className="club-music-start">Use this music</button><button type="button" className="club-music-reset" onClick={closeEditor}>Cancel</button></div>
      </form> : null}
      {storageUnavailable && !editing ? <span role="status">Device storage is unavailable; your choice lasts for this session.</span> : null}
    </div>
  </section>;
}
