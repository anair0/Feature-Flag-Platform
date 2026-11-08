import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, tokenStore } from "./api/client";
import type { Me, Org, Project } from "./api/types";

interface Session {
  me: Me;
  org: Org;
  setOrgId: (id: string) => void;
  projects: Project[];
  logout: () => void;
}

const Ctx = createContext<Session | null>(null);
const ORG_KEY = "ff.org";

export function SessionProvider({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({ queryKey: ["me"], queryFn: api.me, enabled: !!tokenStore.get() });
  const [orgId, setOrgIdState] = useState<string | null>(() => {
    try { return localStorage.getItem(ORG_KEY); } catch { return null; }
  });
  const me = meQuery.data;
  const org = me?.orgs.find((o) => o.id === orgId) ?? me?.orgs[0];
  const projects = useQuery({
    queryKey: ["projects", org?.id],
    queryFn: () => api.projects(org!.id),
    enabled: !!org,
  });

  useEffect(() => {
    if (org && org.id !== orgId) setOrgIdState(org.id);
  }, [org, orgId]);

  if (!tokenStore.get() || meQuery.isError) return <>{fallback}</>;
  if (!me || !org || !projects.data) return <div className="center muted">Loading…</div>;

  const value: Session = {
    me, org, projects: projects.data,
    setOrgId: (id) => {
      try { localStorage.setItem(ORG_KEY, id); } catch { /* ignore */ }
      setOrgIdState(id);
    },
    logout: () => {
      tokenStore.set(null);
      qc.clear();
      window.location.assign("/login");
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}
