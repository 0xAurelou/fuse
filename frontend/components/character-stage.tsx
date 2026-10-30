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

export const CharacterStage = memo(function CharacterStage({ reaction }: { reaction: AvatarReaction | null }) {
  const [paused, setPaused] = useState(false), [hidden, setHidden] = useState(false), [credits, setCredits] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const drag = useRef<{ startX: number; startY: number; baseX: number; baseY: number; grabDX: number; grabDY: number; width: number; height: number } | null>(null);
  const [activeReaction, setActiveReaction] = useState<AvatarReaction['kind'] | null>(null);
  // Drag the companion by its toolbar: buttons keep their clicks, the bar
  // background and label move the whole overlay. Positioning is transform-
  // based and re-anchored from the live bounding box, so it works no matter
  // where the layout parks the companion (fixed overlay or in-flow panel);
  // the box is clamped to stay fully inside the viewport.
  function dragMove(event: PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const desiredX = event.clientX - d.grabDX;
    const desiredY = event.clientY - d.grabDY;
    const x = Math.max(-d.baseX, Math.min(window.innerWidth - d.baseX - d.width, desiredX - d.baseX));
    const y = Math.max(-d.baseY, Math.min(window.innerHeight - d.baseY - d.height, desiredY - d.baseY));
    setPos({ x, y });
  }
  function dragEnd() {
    drag.current = null;
    document.body.style.cursor = '';
    window.removeEventListener('pointermove', dragMove);
  }
  function onToolbarPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('button')) return;
    const aside = event.currentTarget.parentElement!;
    const rect = aside.getBoundingClientRect();
    const current = pos ?? { x: 0, y: 0 };
    drag.current = {
      startX: event.clientX, startY: event.clientY,
      baseX: rect.left - current.x, baseY: rect.top - current.y,
      grabDX: event.clientX - rect.left, grabDY: event.clientY - rect.top,
      width: rect.width, height: rect.height,
    };
    document.body.style.cursor = 'grabbing';
    window.addEventListener('pointermove', dragMove);
    window.addEventListener('pointerup', dragEnd, { once: true });
  }
  useEffect(() => () => { window.removeEventListener('pointermove', dragMove); }, []);
  useEffect(() => {
    const remaining = reaction ? reaction.at + REACTION_SECONDS[reaction.kind] * 1000 - Date.now() : 0;
    if (!reaction || remaining <= 0) { setActiveReaction(null); return; }
    setActiveReaction(reaction.kind);
    const timer = setTimeout(() => setActiveReaction(null), remaining);
    return () => clearTimeout(timer);
  }, [reaction]);
  const stopped = paused;
  const caption = stopped ? 'PAUSED' : activeReaction === 'win' ? 'STAGE WON' : activeReaction === 'loss' ? 'KISS IT GOODBYE' : 'CLASSIC DANCE';
  if (hidden) return <button className="vtuber-restore" onClick={() => setHidden(false)} aria-label="Show VTuber avatar"><Icon name="users" size={14}/><span>VTUBER</span></button>;
  return <aside className="vtuber-companion" aria-label="3D VTuber companion" data-reaction={stopped ? 'paused' : activeReaction || 'idle'} style={pos ? { transform: `translate(${pos.x}px, ${pos.y}px)`, zIndex: 40 } : undefined}>
    <CharacterCanvas options={{ playing: !stopped, reaction }}/>
    <div className="vtuber-toolbar" onPointerDown={onToolbarPointerDown}>
      <span className="vtuber-label" aria-live="polite"><i/>{caption}</span>
      <button aria-label={paused ? 'Resume the dance' : 'Pause the dance'} aria-pressed={paused} onClick={() => setPaused(value => !value)}>{stopped ? '▶' : 'Ⅱ'}</button>
      <button aria-label="Avatar credits" aria-expanded={credits} onClick={() => setCredits(value => !value)}><Icon name="info" size={12}/></button>
      <button aria-label="Minimize VTuber avatar" onClick={() => setHidden(true)}>−</button>
    </div>
    {credits ? <div className="vtuber-credits">Victoria Rubin · CC0 model<br/><a href="/characters/victoria/README.md" target="_blank" rel="noreferrer">Model &amp; renderer credits <Icon name="external" size={10}/></a></div> : null}
  </aside>;
});
