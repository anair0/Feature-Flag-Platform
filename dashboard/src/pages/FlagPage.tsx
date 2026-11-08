import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Flag, FlagConfig, FlagConfigIn } from "../api/types";
import { AuditList } from "../components/AuditList";
import { Evaluator } from "../components/Evaluator";
import { ExperimentPanel } from "../components/Experiment";
import { TargetingEditor } from "../components/Targeting";
import { EnvBadge, ErrorBox, Modal, timeAgo } from "../components/ui";
import { can } from "../permissions";
import { useSession } from "../session";

const toInput = (c: FlagConfig): FlagConfigIn => ({
  on: c.on, off_variation: c.off_variation, targets: c.targets, rules: c.rules, fallthrough: c.fallthrough,
});

type Tab = "targeting" | "experiment" | "history" | "settings";

export function FlagPage() {
  const { org, projects } = useSession();
  const { project: projectKey = "default", flag: flagKey = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const project = projects.find((p) => p.key === projectKey);
  const envKey = params.get("env") ?? project?.environments.find((e) => e.protected)?.key ?? project?.environments[0]?.key ?? "";
  const tab = (params.get("tab") as Tab) ?? "targeting";
  const flag = useQuery({ queryKey: ["flag", org.id, projectKey, flagKey], queryFn: () => api.flag(org.id, projectKey, flagKey) });
  const go = (p: Record<string, string>) => setParams({ env: envKey, tab, ...p });

  if (flag.error) return <div className="page"><ErrorBox error={flag.error} /></div>;
  if (!flag.data || !project) return <div className="page muted">Loading…</div>;
  const env = project.environments.find((e) => e.key === envKey) ?? project.environments[0];
  const cfg = flag.data.environments[env.key];

  return (
    <div className="page">
      <nav className="crumbs"><Link to={`/p/${projectKey}/flags`}>Flags</Link> / <code>{flag.data.key}</code></nav>
      <header className="page-head">
        <div>
          <h1>{flag.data.name} {flag.data.archived && <span className="pill warn">archived</span>}</h1>
          <p className="muted">{flag.data.description || "No description"}</p>
        </div>
        <CodeSnippet flag={flag.data} />
      </header>
      <div className="env-tabs" role="tablist">
        {project.environments.map((e) => (
          <button key={e.key} role="tab" aria-selected={e.key === env.key} className={e.key === env.key ? "active" : ""} onClick={() => go({ env: e.key })}>
            <span className={`dot ${flag.data.environments[e.key]?.on ? "on" : ""}`} /> <EnvBadge name={e.name} protectedEnv={e.protected} />
          </button>
        ))}
      </div>
      <div className="tabs" role="tablist">
        {(["targeting", "experiment", "history", "settings"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={t === tab} className={t === tab ? "active" : ""} onClick={() => go({ tab: t })}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      {tab === "targeting" && cfg && (
        <div className="split">
          <ConfigEditor key={`${env.key}`} flag={flag.data} cfg={cfg} envKey={env.key} protectedEnv={env.protected} projectKey={projectKey} />
          <aside><Evaluator projectKey={projectKey} flag={flag.data} envKey={env.key} version={cfg.version} /></aside>
        </div>
      )}
      {tab === "experiment" && <ExperimentPanel projectKey={projectKey} flag={flag.data} envKey={env.key} />}
      {tab === "history" && <AuditList projectKey={projectKey} flagKey={flag.data.key} />}
      {tab === "settings" && <SettingsPanel projectKey={projectKey} flag={flag.data} />}
    </div>
  );
}

function ConfigEditor({ flag, cfg, envKey, protectedEnv, projectKey }: {
  flag: Flag; cfg: FlagConfig; envKey: string; protectedEnv: boolean; projectKey: string;
}) {
  const { org } = useSession();
  const qc = useQueryClient();
  // The version this draft is based on. Saving sends it as If-Match.
  const [base, setBase] = useState<FlagConfig>(cfg);
  const [draft, setDraft] = useState<FlagConfigIn>(toInput(cfg));
  const [editorKey, setEditorKey] = useState(0);
  const [conflict, setConflict] = useState<FlagConfig | null>(null);
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(toInput(base)), [draft, base]);
  const allowed = can(org.role, "config.update", protectedEnv) && !flag.archived;

  // Someone else saved and we have no local edits: follow along silently.
  useEffect(() => {
    if (cfg.version > base.version && !dirty) {
      setBase(cfg);
      setDraft(toInput(cfg));
      setEditorKey((k) => k + 1);
    }
  }, [cfg, base.version, dirty]);

  const save = useMutation({
    mutationFn: (version: number) => api.saveConfig(org.id, projectKey, flag.key, envKey, version, draft),
    onSuccess: (saved) => {
      setBase(saved);
      setDraft(toInput(saved));
      setEditorKey((k) => k + 1);
      setConflict(null);
      qc.invalidateQueries({ queryKey: ["flag", org.id, projectKey, flag.key] });
      qc.invalidateQueries({ queryKey: ["flags", org.id, projectKey] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        const current = (e.detail as { current?: FlagConfig })?.current;
        if (current) setConflict({ ...current, environment_key: envKey, updated_at: null });
      }
    },
  });

  const discard = () => { setDraft(toInput(base)); setEditorKey((k) => k + 1); };
  const loadLatest = () => {
    if (!conflict) return;
    setBase(conflict);
    setDraft(toInput(conflict));
    setEditorKey((k) => k + 1);
    setConflict(null);
    save.reset();
    qc.invalidateQueries({ queryKey: ["flag", org.id, projectKey, flag.key] });
  };

  return (
    <div>
      {!allowed && (
        <div className="notice">
          {flag.archived ? "Archived flags are read-only." : protectedEnv
            ? `${envKey} is a protected environment: only admins and owners can change it.`
            : "Your role is read-only."}
        </div>
      )}
      <TargetingEditor key={editorKey} draft={draft} variations={flag.variations} readOnly={!allowed} onChange={setDraft} />
      {allowed && (
        <div className={`save-bar ${dirty ? "visible" : ""}`}>
          <span className="muted small">Version {base.version}{base.updated_at ? ` · saved ${timeAgo(base.updated_at)}` : ""}</span>
          {save.error && !(save.error instanceof ApiError && save.error.status === 409) ? <ErrorBox error={save.error} /> : null}
          <button className="ghost" disabled={!dirty || save.isPending} onClick={discard}>Discard</button>
          <button className="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(base.version)}>
            {save.isPending ? "Saving…" : `Save to ${envKey}`}
          </button>
        </div>
      )}
      {conflict && (
        <Modal title="Someone else changed this flag" onClose={() => setConflict(null)} footer={<>
          <button className="ghost" onClick={loadLatest}>Discard mine, load theirs</button>
          <button className="primary danger" onClick={() => save.mutate(conflict.version)}>Overwrite with mine</button>
        </>}>
          <p>While you were editing, version {conflict.version} was saved in <b>{envKey}</b>. Your save was rejected so
            their change isn't silently lost.</p>
          <ConfigDiff before={toInput(conflict)} after={draft} labels={["Theirs (saved)", "Yours (unsaved)"]} />
        </Modal>
      )}
    </div>
  );
}

function ConfigDiff({ before, after, labels }: { before: FlagConfigIn; after: FlagConfigIn; labels: [string, string] }) {
  const keys = (Object.keys(after) as (keyof FlagConfigIn)[]).filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
  if (!keys.length) return <p className="muted">Your draft matches the saved version.</p>;
  return (
    <table className="diff">
      <thead><tr><th /><th>{labels[0]}</th><th>{labels[1]}</th></tr></thead>
      <tbody>{keys.map((k) => (
        <tr key={k}><th>{k}</th><td><pre>{JSON.stringify(before[k], null, 1)}</pre></td><td><pre>{JSON.stringify(after[k], null, 1)}</pre></td></tr>
      ))}</tbody>
    </table>
  );
}

function CodeSnippet({ flag }: { flag: Flag }) {
  const [lang, setLang] = useState<"py" | "ts">("py");
  const def = JSON.stringify(flag.kind === "boolean" ? false : flag.variations[0]);
  const method = { boolean: "bool", string: "string", number: "number", json: "json" }[flag.kind];
  const pyDef = flag.kind === "boolean" ? "False" : def;
  const code = lang === "py"
    ? `client.${method}("${flag.key}", user, default=${pyDef})`
    : `client.${method}("${flag.key}", user, ${def})`;
  return (
    <div className="snippet">
      <div className="snippet-tabs">
        <button className={lang === "py" ? "active" : ""} onClick={() => setLang("py")}>Python</button>
        <button className={lang === "ts" ? "active" : ""} onClick={() => setLang("ts")}>TypeScript</button>
        <button className="ghost small" onClick={() => navigator.clipboard?.writeText(code)}>Copy</button>
      </div>
      <code>{code}</code>
    </div>
  );
}

function SettingsPanel({ projectKey, flag }: { projectKey: string; flag: Flag }) {
  const { org } = useSession();
  const qc = useQueryClient();
  const [name, setName] = useState(flag.name);
  const [description, setDescription] = useState(flag.description);
  const [clientSide, setClientSide] = useState(flag.client_side);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["flag", org.id, projectKey, flag.key] });
    qc.invalidateQueries({ queryKey: ["flags", org.id, projectKey] });
  };
  const update = useMutation({
    mutationFn: () => api.updateFlag(org.id, projectKey, flag.key, { name, description, client_side: clientSide }),
    onSuccess: refresh,
  });
  const archive = useMutation({ mutationFn: () => api.archiveFlag(org.id, projectKey, flag.key, !flag.archived), onSuccess: refresh });
  const canEdit = can(org.role, "flag.update");
  return (
    <div className="card narrow">
      <fieldset disabled={!canEdit}>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Description<textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={clientSide} onChange={(e) => setClientSide(e.target.checked)} />
          Available to browser SDKs</label>
        <p className="muted small">Variations: {flag.variations.map((v) => JSON.stringify(v)).join(", ")} (fixed at creation)</p>
        <ErrorBox error={update.error} />
        <button className="primary" disabled={update.isPending} onClick={() => update.mutate()}>Save settings</button>
      </fieldset>
      <hr />
      <h3>{flag.archived ? "Restore flag" : "Archive flag"}</h3>
      <p className="muted small">{flag.archived
        ? "Restoring puts the flag back in every environment with its last configuration."
        : "Archiving removes the flag from all SDKs. Code that still checks it gets its default value."}</p>
      <ErrorBox error={archive.error} />
      <button className={flag.archived ? "secondary" : "danger"} disabled={!can(org.role, "flag.archive") || archive.isPending}
        onClick={() => (flag.archived || confirm(`Archive ${flag.key}? SDKs will stop receiving it.`)) && archive.mutate()}>
        {flag.archived ? "Restore" : "Archive"}
      </button>
    </div>
  );
}
