export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

/** A user (evaluation context). `id` is required; other keys are attributes. */
export interface User {
  id: string;
  [attribute: string]: unknown;
}

export interface Clause {
  attribute: string;
  op: string;
  values: JsonValue[];
  negate?: boolean;
}

export interface WeightedVariation {
  variation: number;
  weight: number;
}

export interface Rollout {
  kind?: "rollout" | "experiment";
  bucket_by?: string;
  variations: WeightedVariation[];
}

export type Serve = { variation: number } | { rollout: Rollout };

export interface Rule {
  id?: string;
  description?: string;
  clauses: Clause[];
  serve: Serve;
}

export interface Target {
  variation: number;
  values: string[];
}

/** Flag configuration format: spec/flag-config.md */
export interface FlagConfig {
  key: string;
  version: number;
  kind: "boolean" | "string" | "number" | "json";
  on: boolean;
  variations: JsonValue[];
  off_variation: number | null;
  targets: Target[];
  rules: Rule[];
  fallthrough: Serve;
  salt: string;
  client_side: boolean;
}

export type ErrorKind =
  | "USER_NOT_SPECIFIED"
  | "MALFORMED_FLAG"
  | "FLAG_NOT_FOUND"
  | "WRONG_TYPE"
  | "CLIENT_NOT_READY"
  | "EXCEPTION";

export type Reason =
  | { kind: "OFF" }
  | { kind: "TARGET_MATCH" }
  | { kind: "RULE_MATCH"; rule_index: number; rule_id: string | null; in_experiment?: true }
  | { kind: "FALLTHROUGH"; in_experiment?: true }
  | { kind: "ERROR"; error_kind: ErrorKind };

export interface EvaluationDetail<T = JsonValue> {
  value: T;
  variation_index: number | null;
  reason: Reason;
}

export interface Logger {
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}

export const silentLogger: Logger = { warn() {}, error() {} };
