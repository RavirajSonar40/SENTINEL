export default function Footer() {
  return (
    <footer className="h-7 w-full flex items-center bg-surface-container-lowest border-t border-outline-variant px-4 text-[10px] text-on-surface-variant font-mono justify-between shrink-0">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Sentinel v0.1.0
        </span>
        <span className="text-outline-variant">|</span>
        <span>PostgreSQL: Connected</span>
        <span className="text-outline-variant">|</span>
        <span>Qdrant: Connected</span>
      </div>
      <div className="flex items-center gap-3">
        <span>AI Model: kimi-k3</span>
        <span className="text-outline-variant">|</span>
        <span>Uptime: 99.9%</span>
      </div>
    </footer>
  );
}
