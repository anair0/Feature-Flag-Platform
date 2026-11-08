import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Role } from "../api/types";
import { ErrorBox } from "../components/ui";
import { can } from "../permissions";
import { useSession } from "../session";

const ROLES: { role: Role; help: string }[] = [
  { role: "reader", help: "View flags, targeting and history" },
  { role: "writer", help: "Create flags; change targeting outside protected environments" },
  { role: "admin", help: "Everything incl. production, SDK keys and team" },
  { role: "owner", help: "Admin, plus managing owners" },
];

export function MembersPage() {
  const { org, me } = useSession();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members", org.id], queryFn: () => api.members(org.id) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("writer");
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", org.id] });
  const add = useMutation({ mutationFn: () => api.addMember(org.id, email, role), onSuccess: () => { setEmail(""); refresh(); } });
  const change = useMutation({ mutationFn: ({ id, r }: { id: string; r: Role }) => api.setRole(org.id, id, r), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api.removeMember(org.id, id), onSuccess: refresh });
  const manage = can(org.role, "members.manage");
  const assignable = ROLES.filter((r) => org.role === "owner" || r.role !== "owner");

  return (
    <div className="page">
      <header className="page-head"><div><h1>Team</h1><p className="muted">{org.name}</p></div></header>
      <div className="card">
        <table className="members">
          <tbody>
            {(members.data ?? []).map((m) => (
              <tr key={m.user_id}>
                <td><b>{m.name}</b>{m.user_id === me.id && <span className="pill">you</span>}<div className="muted small">{m.email}</div></td>
                <td>
                  <select value={m.role} disabled={!manage || (m.role === "owner" && org.role !== "owner")}
                    onChange={(e) => change.mutate({ id: m.user_id, r: e.target.value as Role })}>
                    {(m.role === "owner" && org.role !== "owner" ? ROLES : assignable).map((r) => <option key={r.role} value={r.role}>{r.role}</option>)}
                  </select>
                </td>
                <td>{manage && <button className="ghost small danger" onClick={() => confirm(`Remove ${m.email}?`) && remove.mutate(m.user_id)}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ErrorBox error={change.error ?? remove.error} />
      </div>
      {manage && (
        <form className="card row" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate(); }}>
          <input type="email" required placeholder="teammate@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {assignable.map((r) => <option key={r.role} value={r.role}>{r.role}</option>)}
          </select>
          <button className="primary" disabled={add.isPending}>Add member</button>
          <ErrorBox error={add.error} />
        </form>
      )}
      <div className="card">
        <h3>Roles</h3>
        <dl className="roles">{ROLES.map((r) => <div key={r.role}><dt>{r.role}</dt><dd className="muted">{r.help}</dd></div>)}</dl>
      </div>
    </div>
  );
}
