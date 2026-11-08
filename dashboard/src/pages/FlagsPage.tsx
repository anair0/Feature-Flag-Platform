import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Flag, FlagConfig, JsonValue } from "../api/types";
import { EnvBadge, ErrorBox, Modal, Toggle, timeAgo } from "../components/ui";
import { can } from "../permissions";
import { useSession } from "../session";

export function FlagsPage() {
  const { org, projects } = useSession();
  const { project: projectKey = "default" } = useParams();
  const project = projects.find((p) => p.key === projectKey);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const flags = useQuery({
    queryKey: ["flags", org.id, projectKey, showArchived],
    queryFn: () => api.flags(org.id, projectKey, showArchived),
    refetchInterval: 5000, // teammates' changes show up without a reload
  });
  const visible = useMemo(
    () => (flags.data ?? []).filter((f) =>
      `${f.key} ${f.name} ${f.description}`.toLowerCase().includes(search.toLowerCase())),
    [flags.data, search],
  );
  if (!project) return <div className="page">Project not found.</div>;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Flags</h1>
          <p className="muted">{project.name} · {flags.data ? `${flags.data.length} flag${flags.data.length === 1 ? "" : "s"}` : "…"}</p>
        </div>
        <button className="primary" disabled={!can(org.role, "flag.create")} onClick={() => setCreating(true)}>
          New flag
        </button>
      </header>
      <div className="toolbar">
        <input className="search" placeholder="Search flags" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="check"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived</label>
      </div>
      <ErrorBox error={flags.error} />
      <div className="card flush">
        <table className="flags-table">
          <thead>
            <tr>
              <th>Flag</th>
              {project.environments.map((e) => <th key={e.key} className="env-col"><EnvBadge name={e.name} protectedEnv={e.protected} /></th>)}
            </tr>
          </thead>
          <tbody>
            {visible.map((flag) => (
              <FlagRow key={flag.key} flag={flag} projectKey={projectKey} envs={project.environments} />
            ))}
            {flags.data && visible.length === 0 && (
              <tr><td colSpan={1 + project.environments.length} className="empty">
                {flags.data.length ? "No flags match your search." : "No flags yet. Create one to get started."}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {creating && <CreateFlagModal projectKey={projectKey} onClose={() => setCreating(false)} />}
    </div>
  );
}

function FlagRow({ flag, projectKey, envs }: { flag: Flag; projectKey: string; envs: { key: string; protected: boolean }[] }) {
  const { org } = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const toggle = useMutation({
    mutationFn: ({ env, cfg }: { env: string; cfg: FlagConfig }) =>
      api.saveConfig(org.id, projectKey, flag.key, env, cfg.version, {
        on: !cfg.on, off_variation: cfg.off_variation, targets: cfg.targets, rules: cfg.rules, fallthrough: cfg.fallthrough,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flags", org.id, projectKey] }),
    onError: (e) => {
      setError(e);
      if (e instanceof ApiError && e.status === 409) qc.invalidateQueries({ queryKey: ["flags", org.id, projectKey] });
    },
  });
  return (
    <tr className={`clickable ${flag.archived ? "archived" : ""}`} onClick={() => navigate(`/p/${projectKey}/flags/${flag.key}`)}>
      <td>
        <Link to={`/p/${projectKey}/flags/${flag.key}`} className="flag-name" onClick={(e) => e.stopPropagation()}>{flag.name}</Link>
        <div className="flag-meta">
          <code>{flag.key}</code>
          <span className="pill">{flag.kind}</span>
          {flag.client_side && <span className="pill" title="Available to browser SDKs">client-side</span>}
          {flag.archived && <span className="pill warn">archived</span>}
          <span className="muted small">created {timeAgo(flag.created_at)}</span>
        </div>
        {error ? <div onClick={(e) => e.stopPropagation()}><ErrorBox error={error} /></div> : null}
      </td>
      {envs.map((env) => {
        const cfg = flag.environments[env.key];
        if (!cfg) return <td key={env.key} />;
        const allowed = can(org.role, "config.update", env.protected) && !flag.archived;
        return (
          <td key={env.key} className="env-col">
            <div className="env-cell">
              <Toggle checked={cfg.on} disabled={!allowed || toggle.isPending}
                label={`${flag.key} in ${env.key}`}
                title={allowed ? undefined : env.protected ? "Production changes need an admin" : "Read-only"}
                onChange={() => { setError(null); toggle.mutate({ env: env.key, cfg }); }} />
              <span className="muted small">{summary(cfg, flag.variations)}</span>
            </div>
          </td>
        );
      })}
    </tr>
  );
}

function summary(cfg: FlagConfig, variations: JsonValue[]): string {
  if (!cfg.on) return "off";
  const parts: string[] = [];
  if (cfg.targets.some((t) => t.values.length)) parts.push("targets");
  if (cfg.rules.length) parts.push(`${cfg.rules.length} rule${cfg.rules.length > 1 ? "s" : ""}`);
  const ft = cfg.fallthrough;
  if (ft.rollout) parts.push(ft.rollout.kind === "experiment" ? "experiment" : "rollout");
  else if (ft.variation !== undefined && !parts.length) parts.push(`→ ${JSON.stringify(variations[ft.variation])}`);
  return parts.join(" · ");
}

function CreateFlagModal({ projectKey, onClose }: { projectKey: string; onClose: () => void }) {
  const { org } = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [kind, setKind] = useState<Flag["kind"]>("boolean");
  const [variationsText, setVariationsText] = useState("control\ntreatment");
  const [description, setDescription] = useState("");
  const [clientSide, setClientSide] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 100);

  const create = useMutation({
    mutationFn: () => {
      let variations: JsonValue[] | undefined;
      if (kind !== "boolean") {
        const lines = variationsText.split("\n").map((l) => l.trim()).filter(Boolean);
        variations = lines.map((l) => (kind === "string" ? l : JSON.parse(l)));
      }
      return api.createFlag(org.id, projectKey, { key, name, description, kind, variations, client_side: clientSide });
    },
    onSuccess: (flag) => {
      qc.invalidateQueries({ queryKey: ["flags", org.id, projectKey] });
      navigate(`/p/${projectKey}/flags/${flag.key}`);
    },
  });

  const submit = () => {
    setParseError(null);
    try {
      if (kind === "number" || kind === "json") variationsText.split("\n").filter((l) => l.trim()).forEach((l) => JSON.parse(l));
    } catch {
      setParseError(kind === "number" ? "Each line must be a number." : "Each line must be valid JSON.");
      return;
    }
    create.mutate();
  };

  return (
    <Modal title="New flag" onClose={onClose} footer={
      <><button className="ghost" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!name || !key || create.isPending} onClick={submit}>Create flag</button></>
    }>
      <label>Name<input autoFocus value={name} onChange={(e) => { setName(e.target.value); if (!keyEdited) setKey(slug(e.target.value)); }} placeholder="New checkout flow" /></label>
      <label>Key <span className="muted small">used in code; can't be changed</span>
        <input value={key} onChange={(e) => { setKeyEdited(true); setKey(e.target.value); }} placeholder="new-checkout" />
      </label>
      <label>Description<textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      <label>Type
        <select value={kind} onChange={(e) => setKind(e.target.value as Flag["kind"])}>
          <option value="boolean">Boolean (on / off)</option>
          <option value="string">String</option>
          <option value="number">Number</option>
          <option value="json">JSON</option>
        </select>
      </label>
      {kind !== "boolean" && (
        <label>Variations <span className="muted small">one per line{kind !== "string" ? ", as JSON" : ""}</span>
          <textarea rows={4} value={variationsText} onChange={(e) => setVariationsText(e.target.value)} className="mono" />
        </label>
      )}
      <label className="check"><input type="checkbox" checked={clientSide} onChange={(e) => setClientSide(e.target.checked)} />
        Available to browser SDKs <span className="muted small">(its evaluated value becomes visible to end users)</span></label>
      <p className="muted small">New flags start <b>off</b> in every environment.</p>
      {parseError && <div className="error-box">{parseError}</div>}
      <ErrorBox error={create.error} />
    </Modal>
  );
}
