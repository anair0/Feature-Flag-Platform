import { NavLink, Navigate, Outlet, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { AuditPage } from "./pages/AuditPage";
import { EnvironmentsPage } from "./pages/EnvironmentsPage";
import { FlagPage } from "./pages/FlagPage";
import { FlagsPage } from "./pages/FlagsPage";
import { LoginPage } from "./pages/LoginPage";
import { MembersPage } from "./pages/MembersPage";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import { can } from "./permissions";
import { SessionProvider, useSession } from "./session";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage mode="login" />} />
      <Route path="/signup" element={<LoginPage mode="signup" />} />
      <Route element={<SessionProvider fallback={<Navigate to="/login" replace />}><Shell /></SessionProvider>}>
        <Route index element={<DefaultProject />} />
        <Route path="p/:project/flags" element={<FlagsPage />} />
        <Route path="p/:project/flags/:flag" element={<FlagPage />} />
        <Route path="p/:project/environments" element={<EnvironmentsPage />} />
        <Route path="members" element={<MembersPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<DefaultProject />} />
      </Route>
    </Routes>
  );
}

function DefaultProject() {
  const { projects } = useSession();
  return <Navigate to={`/p/${projects[0]?.key ?? "default"}/flags`} replace />;
}

function Shell() {
  const { me, org, setOrgId, projects, logout } = useSession();
  const params = useParams();
  const navigate = useNavigate();
  const project = params.project ?? projects[0]?.key;
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="logo" aria-hidden>⚑</span> Flagship</div>
        {me.orgs.length > 1 ? (
          <select className="org-select" value={org.id} onChange={(e) => { setOrgId(e.target.value); navigate("/"); }}>
            {me.orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        ) : <div className="org-name">{org.name}</div>}
        <label className="side-label">Project</label>
        <select value={project} onChange={(e) => navigate(`/p/${e.target.value}/flags`)}>
          {projects.map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
        </select>
        {can(org.role, "project.create") && <NewProjectButton />}
        <nav>
          <NavLink to={`/p/${project}/flags`}>Flags</NavLink>
          <NavLink to={`/p/${project}/environments`}>Environments &amp; keys</NavLink>
          <NavLink to="/audit">Audit log</NavLink>
          <NavLink to="/members">Team</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="who">{me.name}<span className="muted"> · {org.role}</span></div>
          <button className="ghost small" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="content"><Outlet /></main>
    </div>
  );
}

function NewProjectButton() {
  const { org } = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = async () => {
    const name = prompt("Project name");
    if (!name) return;
    const key = name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
    try {
      await api.createProject(org.id, key, name);
      await qc.invalidateQueries({ queryKey: ["projects", org.id] });
      navigate(`/p/${key}/flags`);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };
  return <button className="ghost small side-new" onClick={create}>+ New project</button>;
}
