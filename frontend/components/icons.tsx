export function Icon({ name, size = 18, className = '' }: { name: string; size?: number; className?: string }) {
  const paths: Record<string, React.ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z"/>,
    chart: <><path d="M3 3v18h18M7 15l4-5 4 3 6-8"/></>,
    layers: <><path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
    wallet: <><path d="M20 7V4H5a2 2 0 0 0 0 4h16v12H5a2 2 0 0 1-2-2V6"/><path d="M21 12h-5v4h5"/></>,
    arrow: <><path d="M5 12h14m-5-5 5 5-5 5"/></>,
    external: <><path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/></>,
    down: <path d="m6 9 6 6 6-6"/>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/></>,
    book: <><path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1Zm0 0v15"/></>,
    pulse: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
    globe: <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
    coin: <><circle cx="12" cy="12" r="9"/><path d="m14 7-5 5h6l-5 5"/></>,
    users: <><circle cx="9" cy="8" r="3"/><path d="M3 21v-4a6 6 0 0 1 12 0v4M16 5a3 3 0 0 1 0 6m3 10v-4a6 6 0 0 0-2-4"/></>,
    target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
    refresh: <><path d="M20 7a9 9 0 1 0 1 8M20 3v5h-5"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">{paths[name] || paths.grid}</svg>;
}
