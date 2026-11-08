import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Environment, SdkKey } from "../api/types";
import { EnvBadge, ErrorBox, Modal, Toggle, timeAgo } from "../components/ui";
import { can } from "../permissions";
import { useSession } from "../session";

export function EnvironmentsPage() {
  const { org, projects } = useSession();
  const { project: projectKey = "default" } = useParams();
  const project = projects.find((p) => p.key === projectKey);
  const [creating, setCreating] = useState(false);
  if (!project) return <div className="page">Project not found.</div>;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Environments &amp; SDK keys</h1>
          <p className="muted">Each environment has its own targeting and its own keys.</p></div>
        <button className="primary" disabled={!can(org.role, "environment.create")} onClick={() => setCreating(true)}>New environment</button>
      </header>
      <div className="notice">
        <b>Server SDK keys</b> are secrets: they download your full targeting rules. Keep them on servers.
        <b> Client-side IDs</b> are public and can only fetch evaluated values of flags marked "client-side".
      </div>
      {project.environments.map((e) => <EnvCard key={e.key} env={e} projectKey={projectKey} />)}
      {creating && <CreateEnvModal projectKey={projectKey} onClose={() => setCreating(false)} />}
    </div>
  );
}

function EnvCard({ env, projectKey }: { env: Environment; projectKey: string }) {
  const { org } = useSession();
  const qc = useQueryClient();
  const isAdmin = can(org.role, "keys.read");
  const keys = useQuery({ queryKey: ["keys", org.id, projectKey, env.key], queryFn: () => api.keys(org.id, projectKey, env.key), enabled: isAdmin });
  const [revealed, setRevealed] = useState<SdkKey | null>(null);
  const protect = useMutation({
    mutationFn: (p: boolean) => api.updateEnvironment(org.id, projectKey, env.key, { protected: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", org.id] }),
  });
  const rotate = useMutation({
    mutationFn: ({ kind, grace }: { kind: "server" | "client"; grace: number }) => api.rotateKey(org.id, projectKey, env.key, kind, grace),
    onSuccess: (k) => { setRevealed(k); qc.invalidateQueries({ queryKey: ["keys", org.id, projectKey, env.key] }); },
  });
  return (
    <section className="card env-card">
      <header>
        <h2><EnvBadge name={env.name} protectedEnv={env.protected} /> <code className="muted small">{env.key}</code></h2>
        <label className="inline" title="Protected environments can only be changed by admins and owners">
          Protected <Toggle checked={env.protected} disabled={!can(org.role, "environment.update") || protect.isPending}
            onChange={(v) => protect.mutate(v)} label={`Protect ${env.key}`} />
        </label>
      </header>
      <ErrorBox error={protect.error ?? rotate.error} />
      {!isAdmin ? <p className="muted small">Only admins can view SDK keys.</p> : (
        <table className="keys">
          <tbody>
            {(keys.data ?? []).map((k) => (
              <tr key={k.id}>
                <td>{k.kind === "server" ? "Server SDK key" : "Client-side ID"}</td>
                <td>{k.value ? <CopyCode text={k.value} /> : <code className="muted">{k.hint}</code>}</td>
                <td className="muted small">created {timeAgo(k.created_at)}{k.expires_at && ` · expires ${new Date(k.expires_at).toLocaleString()}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {isAdmin && (
        <div className="row">
          <button className="secondary small" disabled={rotate.isPending} onClick={() => rotate.mutate({ kind: "server", grace: 0 })}>New server key (revoke old now)</button>
          <button className="secondary small" disabled={rotate.isPending} onClick={() => rotate.mutate({ kind: "server", grace: 86400 })}>New server key (old valid 24h)</button>
          <button className="ghost small" disabled={rotate.isPending} onClick={() => confirm("Rotate the client-side ID? Deployed web apps will need the new one.") && rotate.mutate({ kind: "client", grace: 0 })}>Rotate client-side ID</button>
        </div>
      )}
      {revealed && (
        <Modal title="Copy your new key now" onClose={() => setRevealed(null)} footer={<button className="primary" onClick={() => setRevealed(null)}>Done</button>}>
          <p>{revealed.kind === "server" ? "Server keys are stored hashed and won't be shown again." : "New client-side ID:"}</p>
          <CopyCode text={revealed.value ?? ""} />
        </Modal>
      )}
    </section>
  );
}

function CopyCode({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="copy-code">
      <code>{text}</code>
      <button className="ghost small" onClick={() => { navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}

function CreateEnvModal({ projectKey, onClose }: { projectKey: string; onClose: () => void }) {
  const { org } = useSession();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [isProtected, setProtected] = useState(false);
  const [created, setCreated] = useState<{ server_key: string; client_id: string } | null>(null);
  const create = useMutation({
    mutationFn: () => api.createEnvironment(org.id, projectKey, { key, name, protected: isProtected }),
    onSuccess: (r) => { setCreated(r); qc.invalidateQueries({ queryKey: ["projects", org.id] }); },
  });
  if (created) {
    return (
      <Modal title="Environment created" onClose={onClose} footer={<button className="primary" onClick={onClose}>Done</button>}>
        <p>Copy the server key now: it won't be shown again.</p>
        <label>Server SDK key<CopyCode text={created.server_key} /></label>
        <label>Client-side ID<CopyCode text={created.client_id} /></label>
      </Modal>
    );
  }
  return (
    <Modal title="New environment" onClose={onClose} footer={<>
      <button className="ghost" onClick={onClose}>Cancel</button>
      <button className="primary" disabled={!key || !name || create.isPending} onClick={() => create.mutate()}>Create</button></>}>
      <label>Name<input autoFocus value={name} onChange={(e) => { setName(e.target.value); setKey(e.target.value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-")); }} /></label>
      <label>Key<input value={key} onChange={(e) => setKey(e.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={isProtected} onChange={(e) => setProtected(e.target.checked)} /> Protected (admins only)</label>
      <ErrorBox error={create.error} />
    </Modal>
  );
}
