import { useEffect, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { JsonValue } from "../api/types";

export function Toggle({ checked, onChange, disabled, label, title }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string; title?: string;
}) {
  return (
    <button
      type="button" role="switch" aria-checked={checked} aria-label={label} title={title}
      className={`toggle ${checked ? "on" : ""}`} disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onChange(!checked); }}
    >
      <span className="knob" />
    </button>
  );
}

export function Modal({ title, onClose, children, footer }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header><h2>{title}</h2><button className="ghost icon" onClick={onClose} aria-label="Close">×</button></header>
        <div className="modal-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const messages = error instanceof ApiError ? error.messages : [String(error)];
  return (
    <div className="error-box" role="alert">
      {messages.map((m, i) => <div key={i}>{m}</div>)}
    </div>
  );
}

export function Value({ v }: { v: JsonValue }) {
  const text = typeof v === "string" ? v : JSON.stringify(v);
  return <code className={`value value-${typeof v}`}>{text}</code>;
}

export function EnvBadge({ name, protectedEnv }: { name: string; protectedEnv?: boolean }) {
  return (
    <span className={`env-badge ${protectedEnv ? "protected" : ""}`} title={protectedEnv ? "Protected: admins only" : undefined}>
      {protectedEnv && <span aria-hidden>🔒 </span>}{name}
    </span>
  );
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export const pct = (weight: number) => `${(weight / 1000).toFixed(weight % 1000 ? 1 : 0)}%`;
