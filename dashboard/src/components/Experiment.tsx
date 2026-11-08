import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Flag } from "../api/types";
import { VariationName } from "./Targeting";
import { ErrorBox } from "./ui";
import { useSession } from "../session";

const p100 = (x: number) => `${(x * 100).toFixed(2)}%`;

export function ExperimentPanel({ projectKey, flag, envKey }: { projectKey: string; flag: Flag; envKey: string }) {
  const { org } = useSession();
  const [metric, setMetric] = useState("purchase");
  const [minSample, setMinSample] = useState(100);
  const q = useQuery({
    queryKey: ["experiment", org.id, projectKey, flag.key, envKey, metric, minSample],
    queryFn: () => api.experiment(org.id, projectKey, flag.key, envKey, metric, minSample),
    enabled: !!metric,
    refetchInterval: 10_000,
    retry: false,
  });

  return (
    <div>
      <div className="toolbar">
        <label className="inline">Metric <input value={metric} onChange={(e) => setMetric(e.target.value)} className="short" /></label>
        <label className="inline" title="Fix this before you start: don't stop the test at the first significant result">
          Planned users per variation <input type="number" min={1} value={minSample} onChange={(e) => setMinSample(Number(e.target.value) || 1)} className="short" />
        </label>
      </div>
      {q.error instanceof ApiError && q.error.status === 409 ? (
        <div className="card empty">
          <p>{q.error.message}</p>
          <p className="muted small">On the Targeting tab, set a rule or the default rule to a percentage rollout and tick
            "Run as experiment". SDKs then record which variation each user saw.</p>
        </div>
      ) : <ErrorBox error={q.error} />}
      {q.data && (
        <>
          <div className={`verdict ${q.data.conclusive ? "ok" : "wait"}`}>
            {q.data.conclusive
              ? q.data.comparisons.some((c) => c.significant)
                ? "Conclusive: at least one variation differs from control."
                : "Conclusive: no significant difference detected."
              : "Not conclusive yet."}
          </div>
          {q.data.warnings.map((w, i) => <div key={i} className="notice warn">{w}</div>)}
          <div className="card flush">
            <table className="results">
              <thead><tr><th>Variation</th><th>Users</th><th>Expected share</th><th>Converted</th><th>Rate (95% CI)</th>
                <th>Lift vs control</th><th>p (adjusted)</th></tr></thead>
              <tbody>
                {q.data.variations.map((v) => {
                  const c = q.data!.comparisons.find((x) => x.variation_index === v.variation_index);
                  const total = q.data!.variations.reduce((s, x) => s + x.users, 0) || 1;
                  return (
                    <tr key={v.variation_index}>
                      <td><VariationName variations={flag.variations} index={v.variation_index} />
                        {v.variation_index === q.data!.control && <span className="pill">control</span>}</td>
                      <td>{v.users.toLocaleString()} <span className="muted small">({p100(v.users / total)})</span></td>
                      <td>{p100(v.expected_share)}</td>
                      <td>{v.conversions.toLocaleString()}</td>
                      <td>{p100(v.conversion_rate)} <span className="muted small">[{p100(v.conversion_rate_ci[0])}, {p100(v.conversion_rate_ci[1])}]</span></td>
                      <td>{c ? (c.relative_lift === null ? "—" : `${c.relative_lift >= 0 ? "+" : ""}${(c.relative_lift * 100).toFixed(1)}%`) : ""}</td>
                      <td>{c ? <span className={c.significant ? "sig" : ""}>{c.p_value_adjusted.toFixed(4)}{c.significant ? " ✓" : ""}</span> : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Sample-ratio check: χ² = {q.data.srm.chi_square.toFixed(2)}, p = {q.data.srm.p_value.toPrecision(3)}
            {q.data.srm.mismatch ? " (mismatch!)" : " (ok)"} · α = {q.data.alpha} · p-values Bonferroni-adjusted for {Math.max(1, q.data.comparisons.length)} comparison(s)
            · only conversions after a user's first exposure count.
          </p>
        </>
      )}
    </div>
  );
}
