'use client';

import { memo, useEffect, useRef, useState } from 'react';
import { Icon } from './icons';
import { REACTION_SECONDS } from '@/lib/vtuber-motion';
import type { AvatarReaction } from '@/lib/avatar-events';
import type { CharacterOptions, CharacterRenderer } from '@/lib/character-renderer';

const CharacterCanvas = memo(function CharacterCanvas({ options }: { options: CharacterOptions }) {
  const host = useRef<HTMLDivElement>(null), renderer = useRef<CharacterRenderer | null>(null), latest = useRef(options);
  latest.current = options;
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  useEffect(() => {
    const abort = new AbortController();
    async function start() {
      try {
        const { createCharacterRenderer } = await import('@/lib/character-renderer');
        if (!host.current || abort.signal.aborted) return;
        const scene = await createCharacterRenderer(host.current, latest.current, abort.signal);
        if (abort.signal.aborted) { scene?.destroy(); return; }
        renderer.current = scene; scene?.setOptions(latest.current); setStatus('ready');
      } catch { if (!abort.signal.aborted) setStatus('error'); }
    }
    void start();
    return () => { abort.abort(); renderer.current?.destroy(); renderer.current = null; };
  }, []);
  useEffect(() => { renderer.current?.setOptions(options); }, [options]);
  return <div className="vtuber-canvas" ref={host}>
    {status !== 'ready' ? <span className="vtuber-status" role="status">{status === 'loading' ? 'Getting ready…' : '3D avatar unavailable'}</span> : null}
  </div>;
});

export const CharacterStage = memo(function CharacterStage({ playing, reaction }: { playing: boolean; reaction: AvatarReaction | null }) {
  const [paused, setPaused] = useState(false), [hidden, setHidden] = useState(false), [credits, setCredits] = useState(false), [neutral, setNeutral] = useState(false);
  const [activeReaction, setActiveReaction] = useState<AvatarReaction['kind'] | null>(null);
  useEffect(() => {
    const remaining = reaction ? reaction.at + REACTION_SECONDS[reaction.kind] * 1000 - Date.now() : 0;
    if (!reaction || remaining <= 0) { setActiveReaction(null); return; }
    setActiveReaction(reaction.kind);
    const timer = setTimeout(() => setActiveReaction(null), remaining);
    return () => clearTimeout(timer);
  }, [reaction]);
  const stopped = !playing || paused;
  const caption = stopped ? 'PAUSED' : neutral ? 'NEUTRAL POSE' : activeReaction === 'entry' ? 'POSITION OPEN' : activeReaction === 'win' ? 'STAGE WON' : activeReaction === 'loss' ? 'KISS IT GOODBYE' : 'IDLE GROOVE';
  if (hidden) return <button className="vtuber-restore" onClick={() => setHidden(false)} aria-label="Show VTuber avatar"><Icon name="users" size={14}/><span>VTUBER</span></button>;
  return <aside className="vtuber-companion" aria-label="3D VTuber companion" data-reaction={stopped ? 'paused' : activeReaction || 'idle'}>
    <CharacterCanvas options={{ playing: !stopped, reaction, neutral }}/>
    <div className="vtuber-toolbar">
      <span className="vtuber-label" aria-live="polite"><i/>{caption}</span>
      <button disabled={!playing} aria-label={!playing ? 'Avatar paused with DJ' : paused ? 'Resume avatar motion' : 'Pause avatar motion'} aria-pressed={paused} onClick={() => setPaused(value => !value)}>{stopped ? '▶' : 'Ⅱ'}</button>
      <button aria-label={neutral ? 'Resume the dance' : 'Hold a neutral pose'} aria-pressed={neutral} onClick={() => setNeutral(value => !value)}>{neutral ? '♪' : 'T'}</button>
      <button aria-label="Avatar credits" aria-expanded={credits} onClick={() => setCredits(value => !value)}><Icon name="info" size={12}/></button>
      <button aria-label="Minimize VTuber avatar" onClick={() => setHidden(true)}>−</button>
    </div>
    {credits ? <div className="vtuber-credits">Victoria Rubin · CC0 model<br/><a href="/characters/victoria/README.md" target="_blank" rel="noreferrer">Model &amp; renderer credits <Icon name="external" size={10}/></a></div> : null}
  </aside>;
});
