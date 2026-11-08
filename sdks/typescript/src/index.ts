export { FlagClient, type FlagClientOptions } from "./server.js";
export { evaluate, bucket, OPERATORS } from "./evaluation.js";
export type {
  EvaluationDetail,
  FlagConfig,
  JsonValue,
  Logger,
  Reason,
  User,
} from "./types.js";

export const VERSION = "0.1.0";
