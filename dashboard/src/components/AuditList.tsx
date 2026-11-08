import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AuditEntry, JsonValue } from "../api/types";
import { ErrorBox, timeAgo } from "./ui";
import { useSession } from "../session";

const LABELS: Record<string, string> = {
  "flag.created": "created the flag",
  "flag.updated": "edited flag settings",
  "flag.archived": "archived the flag",
  "flag.restored": "restored the flag",
  "config.updated": "changed targeting",
  "environment.created": "created environment",
  "environment.updated": "edited environment",
  "keys.rotated": "rotated an SDK key",
  "member.added": "added a member",
  "member.role_changed": "changed a role",
  "member.removed": "removed a member",
  "project.created": "created a project",
  "org.created": "created the organization",
};

export function AuditList({ projectKey, flagKey }: { projectKey?: string; flagKey?: string }) {
  const { org } = useSession();
  const q = useQuery({
    queryKey: ["audit", org.id, projectKey, flagKey],
    queryFn: () => api.audit(org.id, { project_key: projectKey, flag_key: flagKey, limit: 100 }),
  });
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return <div className="muted">Loading…</div>;
  if (!q.data.length) return <div className="card empty">No changes recorded yet.</div>;
  return (
    <ol className="audit">
      {q.data.map((e) => <AuditItem key={e.id} entry={e} showResource={!flagKey} />)}
    </ol>
  );
}

function AuditItem({ entry, showResource }: { entry: AuditEntry; showResource: boolean }) {
  const changes = diff(entry.before, entry.after);
  return (
    <li className="card audit-item">
      <div className="audit-head">
        <b>{entry.actor_email ?? "system"}</b> {LABELS[entry.action] ?? entry.action}
        {showResource && <> <code>{entry.resource_key}</code></>}
        {entry.environment_key && <> in <span className="env-badge">{entry.environment_key}</span></>}
        <span className="muted small right" title={new Date(entry.created_at).toLocaleString()}>{timeAgo(entry.created_at)}</span>
      </div>
      {changes.length > 0 && (
        <table className="diff compact">
          <tbody>
            {changes.map(([k, b, a]) => (
              <tr key={k}>
                <th>{k}</th>
                <td className="old"><pre>{fmt(b)}</pre></td>
                <td className="arrow">→</td>
                <td className="new"><pre>{fmt(a)}</pre></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

const fmt = (v: JsonValue | undefined) => (v === undefined ? "—" : JSON.stringify(v, null, 1));

function diff(before: JsonValue, after: JsonValue): [string, JsonValue | undefined, JsonValue | undefined][] {
  const obj = (v: JsonValue) => (v && typeof v === "object" && !Array.isArray(v) ? v : {}) as Record<string, JsonValue>;
  const b = obj(before);
  const a = obj(after);
  return [...new Set([...Object.keys(b), ...Object.keys(a)])]
    .filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]))
    .map((k) => [k, b[k], a[k]]);
}
