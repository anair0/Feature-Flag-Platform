// Mirrors backend/app/schemas. Kept by hand; see docs/design-decisions.md for why.

export type Role = "reader" | "writer" | "admin" | "owner";
export type JsonValue = null | boolean | number | string | JsonValue[] | { [k: string]: JsonValue };

export interface Org { id: string; name: string; role: Role }
export interface Me { id: string; email: string; name: string; orgs: Org[] }

export interface Environment {
  id: string; key: string; name: string; protected: boolean; sort_order: number; data_version: number;
}
export interface Project { id: string; key: string; name: string; environments: Environment[] }

export interface Clause { attribute: string; op: string; values: (string | number | boolean)[]; negate: boolean }
export interface WeightedVariation { variation: number; weight: number }
export interface Rollout { kind: "rollout" | "experiment"; bucket_by?: string; variations: WeightedVariation[] }
export type Serve = { variation: number; rollout?: undefined } | { rollout: Rollout; variation?: undefined };
export interface Rule { id?: string; description?: string; clauses: Clause[]; serve: Serve }
export interface Target { variation: number; values: string[] }

export interface FlagConfigIn {
  on: boolean; off_variation: number | null; targets: Target[]; rules: Rule[]; fallthrough: Serve;
}
export interface FlagConfig extends FlagConfigIn {
  environment_key: string; version: number; updated_at: string | null;
}
export interface Flag {
  id: string; key: string; name: string; description: string;
  kind: "boolean" | "string" | "number" | "json"; variations: JsonValue[];
  client_side: boolean; archived: boolean; created_at: string;
  environments: Record<string, FlagConfig>;
}

export interface SdkKey {
  id: string; kind: "server" | "client"; hint: string; value: string | null;
  created_at: string; expires_at: string | null;
}
export interface Member { user_id: string; email: string; name: string; role: Role }
export interface AuditEntry {
  id: number; action: string; resource_type: string; resource_key: string;
  environment_key: string | null; actor_email: string | null;
  before: JsonValue; after: JsonValue; created_at: string;
}

export type Reason =
  | { kind: "OFF" } | { kind: "TARGET_MATCH" }
  | { kind: "RULE_MATCH"; rule_index: number; rule_id: string | null; in_experiment?: true }
  | { kind: "FALLTHROUGH"; in_experiment?: true }
  | { kind: "ERROR"; error_kind: string };
export interface EvaluationResult { value: JsonValue; variation_index: number | null; reason: Reason }

export interface ExperimentResults {
  metric: string; control: number; alpha: number; min_sample: number; conclusive: boolean;
  warnings: string[];
  srm: { chi_square: number; p_value: number; mismatch: boolean };
  variations: {
    variation_index: number; value: JsonValue; users: number; conversions: number;
    conversion_rate: number; conversion_rate_ci: [number, number]; mean_value_per_user: number;
    expected_share: number;
  }[];
  comparisons: {
    variation_index: number; relative_lift: number | null; absolute_difference: number;
    p_value: number; p_value_adjusted: number; significant: boolean;
  }[];
}
