import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EvaluationResult, Flag } from "../api/types";
import { VariationName } from "./Targeting";
import { ErrorBox } from "./ui";
import { useSession } from "../session";

export function explain(r: EvaluationResult): string {
  const reason = r.reason;
  switch (reason.kind) {
    case "OFF": return "Targeting is off, so the off variation was served.";
    case "TARGET_MATCH": return "This user ID is individually targeted.";
    case "RULE_MATCH":
      return `Matched rule ${reason.rule_index + 1}${reason.rule_id ? ` (${reason.rule_id})` : ""}${reason.in_experiment ? "; in experiment" : ""}.`;
    case "FALLTHROUGH": return `No rule matched, so the default rule was applied${reason.in_experiment ? "; in experiment" : ""}.`;
    case "ERROR": return `Error: ${reason.error_kind}. The SDK would return the default passed in code.`;
  }
}

/** "What would this user get, and why?" Evaluated by the server with the saved config. */
export function Evaluator({ projectKey, flag, envKey, version }: { projectKey: string; flag: Flag; envKey: string; version: number }) {
  const { org } = useSession();
  const [text, setText] = useState('{\n  "id": "user-123",\n  "country": "CA",\n  "plan": "pro"\n}');
  const [parseError, setParseError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (user: object) => api.evaluate(org.id, projectKey, flag.key, envKey, user),
  });
  const evaluate = () => {
    try {
      setParseError(null);
      run.mutate(JSON.parse(text));
    } catch {
      setParseError("Not valid JSON");
    }
  };
  // Re-run after each save so the answer reflects the current version.
  useEffect(() => { if (run.data) evaluate(); }, [version, envKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="card evaluator">
      <h3>Test a user</h3>
      <p className="muted small">Uses the <b>saved</b> config in {envKey}.</p>
      <textarea className="mono" rows={7} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <button className="secondary" onClick={evaluate} disabled={run.isPending}>Evaluate</button>
      {parseError && <div className="error-box small">{parseError}</div>}
      <ErrorBox error={run.error} />
      {run.data && (
        <div className="eval-result">
          <div className="eval-value">
            {run.data.variation_index !== null
              ? <VariationName variations={flag.variations} index={run.data.variation_index} />
              : <span className="muted">default value from code</span>}
          </div>
          <div className="small">{explain(run.data)}</div>
          <code className="small muted">{JSON.stringify(run.data.reason)}</code>
        </div>
      )}
    </div>
  );
}
