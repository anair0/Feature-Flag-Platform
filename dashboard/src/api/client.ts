import type {
  AuditEntry, EvaluationResult, ExperimentResults, Flag, FlagConfig, FlagConfigIn, Me, Member,
  Project, Role, SdkKey,
} from "./types";

const TOKEN_KEY = "ff.token";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message ?? `HTTP ${status}`);
  }
  /** FastAPI 422 bodies → readable strings */
  get messages(): string[] {
    const d = this.detail as any;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`);
    if (d?.errors) return d.errors;
    return [this.message];
  }
}

export const tokenStore = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string | null) => {
    try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
  },
};

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const token = tokenStore.get();
  const res = await fetch(path, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && token) {
    tokenStore.set(null);
    window.location.assign("/login");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

const org = (orgId: string) => `/api/orgs/${orgId}`;
const proj = (orgId: string, p: string) => `${org(orgId)}/projects/${p}`;

export const api = {
  signup: (body: { email: string; password: string; name: string; org_name: string }) =>
    request<{ token: string }>("POST", "/api/auth/signup", body),
  login: (email: string, password: string) =>
    request<{ token: string }>("POST", "/api/auth/login", { email, password }),
  me: () => request<Me>("GET", "/api/me"),

  projects: (o: string) => request<Project[]>("GET", `${org(o)}/projects`),
  createProject: (o: string, key: string, name: string) =>
    request<Project>("POST", `${org(o)}/projects`, { key, name }),
  createEnvironment: (o: string, p: string, body: { key: string; name: string; protected: boolean }) =>
    request<{ server_key: string; client_id: string }>("POST", `${proj(o, p)}/environments`, body),
  updateEnvironment: (o: string, p: string, env: string, body: { protected?: boolean; name?: string }) =>
    request("PATCH", `${proj(o, p)}/environments/${env}`, body),
  keys: (o: string, p: string, env: string) => request<SdkKey[]>("GET", `${proj(o, p)}/environments/${env}/keys`),
  rotateKey: (o: string, p: string, env: string, kind: "server" | "client", grace_seconds = 0) =>
    request<SdkKey>("POST", `${proj(o, p)}/environments/${env}/keys/rotate`, { kind, grace_seconds }),

  flags: (o: string, p: string, archived = false) =>
    request<Flag[]>("GET", `${proj(o, p)}/flags?include_archived=${archived}`),
  flag: (o: string, p: string, key: string) => request<Flag>("GET", `${proj(o, p)}/flags/${key}`),
  createFlag: (o: string, p: string, body: Partial<Flag> & { key: string; name: string }) =>
    request<Flag>("POST", `${proj(o, p)}/flags`, body),
  updateFlag: (o: string, p: string, key: string, body: { name?: string; description?: string; client_side?: boolean }) =>
    request<Flag>("PATCH", `${proj(o, p)}/flags/${key}`, body),
  archiveFlag: (o: string, p: string, key: string, archived: boolean) =>
    request<Flag>("POST", `${proj(o, p)}/flags/${key}/archive?archived=${archived}`),
  saveConfig: (o: string, p: string, key: string, env: string, version: number, body: FlagConfigIn) =>
    request<FlagConfig>("PUT", `${proj(o, p)}/flags/${key}/environments/${env}`, body, { "If-Match": `"${version}"` }),
  evaluate: (o: string, p: string, key: string, env: string, user: object) =>
    request<EvaluationResult>("POST", `${proj(o, p)}/flags/${key}/environments/${env}/evaluate`, { user }),
  experiment: (o: string, p: string, key: string, env: string, metric: string, minSample: number) =>
    request<ExperimentResults>("GET",
      `${proj(o, p)}/flags/${key}/environments/${env}/experiment?metric=${encodeURIComponent(metric)}&min_sample=${minSample}`),

  audit: (o: string, params: { project_key?: string; flag_key?: string; limit?: number }) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][]);
    return request<AuditEntry[]>("GET", `${org(o)}/audit?${q}`);
  },
  members: (o: string) => request<Member[]>("GET", `${org(o)}/members`),
  addMember: (o: string, email: string, role: Role) => request<Member>("POST", `${org(o)}/members`, { email, role }),
  setRole: (o: string, userId: string, role: Role) => request<Member>("PATCH", `${org(o)}/members/${userId}`, { role }),
  removeMember: (o: string, userId: string) => request<void>("DELETE", `${org(o)}/members/${userId}`),
};
