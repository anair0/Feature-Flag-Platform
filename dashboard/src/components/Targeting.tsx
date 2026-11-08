import { useEffect, useState } from "react";
import type { Clause, FlagConfigIn, JsonValue, Rollout, Rule, Serve } from "../api/types";
import { Toggle, Value, pct } from "./ui";

const OPS: { op: string; label: string; type: "any" | "string" | "number" | "semver" }[] = [
  { op: "in", label: "is one of", type: "any" },
  { op: "starts_with", label: "starts with", type: "string" },
  { op: "ends_with", label: "ends with", type: "string" },
  { op: "contains", label: "contains", type: "string" },
  { op: "lt", label: "<", type: "number" },
  { op: "lte", label: "≤", type: "number" },
  { op: "gt", label: ">", type: "number" },
  { op: "gte", label: "≥", type: "number" },
  { op: "semver_eq", label: "version =", type: "semver" },
  { op: "semver_lt", label: "version <", type: "semver" },
  { op: "semver_gt", label: "version >", type: "semver" },
];

const COLORS = ["#4f7cff", "#e0884b", "#3fb68b", "#b36ae2", "#d4566b", "#2ab3c7"];
export const variationColor = (i: number) => COLORS[i % COLORS.length];

export function VariationName({ variations, index }: { variations: JsonValue[]; index: number }) {
  return (
    <span className="variation-name">
      <span className="swatch" style={{ background: variationColor(index) }} />
      <Value v={variations[index]} />
    </span>
  );
}

interface EditorProps {
  draft: FlagConfigIn;
  variations: JsonValue[];
  readOnly: boolean;
  onChange: (next: FlagConfigIn) => void;
}

export function TargetingEditor({ draft, variations, readOnly, onChange }: EditorProps) {
  const set = (patch: Partial<FlagConfigIn>) => onChange({ ...draft, ...patch });
  const setRule = (i: number, rule: Rule | null) => {
    const rules = [...draft.rules];
    if (rule) rules[i] = rule;
    else rules.splice(i, 1);
    set({ rules });
  };
  const move = (i: number, d: -1 | 1) => {
    const rules = [...draft.rules];
    [rules[i], rules[i + d]] = [rules[i + d], rules[i]];
    set({ rules });
  };

  return (
    <fieldset disabled={readOnly} className="targeting">
      <section className={`card switch-card ${draft.on ? "is-on" : ""}`}>
        <Toggle checked={draft.on} onChange={(on) => set({ on })} disabled={readOnly} label="Targeting" />
        <div>
          <h3>{draft.on ? "Targeting is ON" : "Targeting is OFF"}</h3>
          <p className="muted small">
            {draft.on ? "Users are evaluated against the rules below." : "Everyone gets the off variation. Rules below are kept but ignored."}
          </p>
        </div>
      </section>

      <section className="card">
        <h3>Individual targets</h3>
        <p className="muted small">Specific user IDs, checked before any rule.</p>
        {variations.map((_, i) => (
          <TargetRow key={i} index={i} variations={variations}
            values={draft.targets.find((t) => t.variation === i)?.values ?? []}
            onChange={(values) => set({
              targets: [...draft.targets.filter((t) => t.variation !== i), ...(values.length ? [{ variation: i, values }] : [])]
                .sort((a, b) => a.variation - b.variation),
            })} />
        ))}
      </section>

      <section>
        <div className="section-head">
          <h3>Rules</h3>
          <span className="muted small">Evaluated top to bottom; the first match wins.</span>
        </div>
        {draft.rules.map((rule, i) => (
          <RuleEditor key={rule.id ?? `new-${i}`} index={i} rule={rule} variations={variations}
            onChange={(r) => setRule(i, r)} onRemove={() => setRule(i, null)}
            onUp={i > 0 ? () => move(i, -1) : undefined}
            onDown={i < draft.rules.length - 1 ? () => move(i, 1) : undefined} />
        ))}
        {!readOnly && (
          <button className="secondary" onClick={() => set({
            rules: [...draft.rules, { clauses: [{ attribute: "country", op: "in", values: [], negate: false }], serve: { variation: 0 } }],
          })}>+ Add rule</button>
        )}
      </section>

      <section className="card">
        <h3>Default rule</h3>
        <p className="muted small">When targeting is on and nothing above matched.</p>
        <ServeEditor serve={draft.fallthrough} variations={variations} onChange={(fallthrough) => set({ fallthrough })} />
      </section>

      <section className="card">
        <h3>When targeting is off, serve</h3>
        <select value={draft.off_variation ?? ""} onChange={(e) => set({ off_variation: e.target.value === "" ? null : Number(e.target.value) })}>
          {variations.map((v, i) => <option key={i} value={i}>{JSON.stringify(v)}</option>)}
          <option value="">the default value passed in code</option>
        </select>
      </section>
    </fieldset>
  );
}

function TargetRow({ index, variations, values, onChange }: {
  index: number; variations: JsonValue[]; values: string[]; onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState(values.join(", "));
  useEffect(() => setText(values.join(", ")), [values.join("\u0000")]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="target-row">
      <VariationName variations={variations} index={index} />
      <input placeholder="user-123, user-456" value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => onChange([...new Set(text.split(/[\s,]+/).filter(Boolean))])} />
    </div>
  );
}

function RuleEditor({ index, rule, variations, onChange, onRemove, onUp, onDown }: {
  index: number; rule: Rule; variations: JsonValue[]; onChange: (r: Rule) => void;
  onRemove: () => void; onUp?: () => void; onDown?: () => void;
}) {
  const setClause = (i: number, c: Clause | null) => {
    const clauses = [...rule.clauses];
    if (c) clauses[i] = c;
    else clauses.splice(i, 1);
    onChange({ ...rule, clauses });
  };
  return (
    <div className="card rule">
      <header>
        <span className="rule-num">Rule {index + 1}</span>
        <input className="rule-desc" placeholder="Description (optional)" value={rule.description ?? ""}
          onChange={(e) => onChange({ ...rule, description: e.target.value })} />
        <div className="rule-actions">
          <button className="ghost icon" disabled={!onUp} onClick={onUp} aria-label="Move up">↑</button>
          <button className="ghost icon" disabled={!onDown} onClick={onDown} aria-label="Move down">↓</button>
          <button className="ghost icon danger" onClick={onRemove} aria-label="Delete rule">🗑</button>
        </div>
      </header>
      {rule.clauses.map((c, i) => (
        <div key={i} className="clause-line">
          <span className="clause-joiner">{i === 0 ? "If" : "and"}</span>
          <ClauseEditor clause={c} onChange={(nc) => setClause(i, nc)} onRemove={rule.clauses.length > 1 ? () => setClause(i, null) : undefined} />
        </div>
      ))}
      <button className="link small" onClick={() => onChange({ ...rule, clauses: [...rule.clauses, { attribute: "", op: "in", values: [], negate: false }] })}>
        + and condition
      </button>
      <div className="serve-line"><span className="clause-joiner">serve</span>
        <ServeEditor serve={rule.serve} variations={variations} onChange={(serve) => onChange({ ...rule, serve })} />
      </div>
    </div>
  );
}

type ValueType = "string" | "number" | "boolean";

function inferType(c: Clause): ValueType {
  const op = OPS.find((o) => o.op === c.op);
  if (op?.type === "number") return "number";
  if (op?.type !== "any") return "string";
  const first = c.values[0];
  return typeof first === "number" ? "number" : typeof first === "boolean" ? "boolean" : "string";
}

function parseValues(text: string, type: ValueType): (string | number | boolean)[] {
  const parts = text.split(",").map((s) => s.trim()).filter((s) => s !== "");
  if (type === "number") return parts.map(Number).filter((n) => !Number.isNaN(n));
  if (type === "boolean") return parts.map((s) => s.toLowerCase() === "true");
  return parts;
}

function ClauseEditor({ clause, onChange, onRemove }: { clause: Clause; onChange: (c: Clause) => void; onRemove?: () => void }) {
  const [type, setType] = useState<ValueType>(inferType(clause));
  const [text, setText] = useState(clause.values.join(", "));
  const opInfo = OPS.find((o) => o.op === clause.op);
  const commit = (t = text, ty = type) => onChange({ ...clause, values: parseValues(t, ty) });
  return (
    <div className="clause">
      <input className="attr" placeholder="attribute" value={clause.attribute} list="known-attributes"
        onChange={(e) => onChange({ ...clause, attribute: e.target.value })} />
      <select value={clause.negate ? "not" : ""} onChange={(e) => onChange({ ...clause, negate: e.target.value === "not" })}>
        <option value="">is</option><option value="not">is not</option>
      </select>
      <select value={clause.op} onChange={(e) => {
        const info = OPS.find((o) => o.op === e.target.value)!;
        const ty: ValueType = info.type === "number" ? "number" : info.type === "any" ? type : "string";
        setType(ty);
        onChange({ ...clause, op: e.target.value, values: parseValues(text, ty) });
      }}>
        {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
      </select>
      <input className="vals" placeholder={opInfo?.type === "semver" ? "2.4.0" : "CA, US"} value={text}
        onChange={(e) => setText(e.target.value)} onBlur={() => commit()} />
      {opInfo?.type === "any" && (
        <select className="type" value={type} title="Value type" onChange={(e) => { const t = e.target.value as ValueType; setType(t); commit(text, t); }}>
          <option value="string">text</option><option value="number">number</option><option value="boolean">bool</option>
        </select>
      )}
      {onRemove && <button className="ghost icon" onClick={onRemove} aria-label="Remove condition">×</button>}
      <datalist id="known-attributes">
        {["id", "country", "plan", "email", "app_version", "groups", "company"].map((a) => <option key={a} value={a} />)}
      </datalist>
    </div>
  );
}

export function ServeEditor({ serve, variations, onChange }: { serve: Serve; variations: JsonValue[]; onChange: (s: Serve) => void }) {
  const mode = serve.rollout ? "rollout" : String(serve.variation);
  const select = (v: string) => {
    if (v !== "rollout") return onChange({ variation: Number(v) });
    const even = Math.floor(100000 / variations.length);
    onChange({ rollout: { kind: "rollout", variations: variations.map((_, i) => ({
      variation: i, weight: i === 0 ? 100000 - even * (variations.length - 1) : even })) } });
  };
  return (
    <div className="serve">
      <select value={mode} onChange={(e) => select(e.target.value)}>
        {variations.map((v, i) => <option key={i} value={i}>{JSON.stringify(v)}</option>)}
        <option value="rollout">a percentage rollout</option>
      </select>
      {serve.rollout && <RolloutEditor rollout={serve.rollout} variations={variations} onChange={(rollout) => onChange({ rollout })} />}
    </div>
  );
}

function RolloutEditor({ rollout, variations, onChange }: { rollout: Rollout; variations: JsonValue[]; onChange: (r: Rollout) => void }) {
  const weightOf = (i: number) => rollout.variations.find((w) => w.variation === i)?.weight ?? 0;
  const total = variations.reduce<number>((s, _, i) => s + weightOf(i), 0);
  const setWeight = (i: number, percent: number) => {
    const weight = Math.round(Math.max(0, Math.min(100, percent)) * 1000);
    const next = variations.map((_, j) => ({ variation: j, weight: j === i ? weight : weightOf(j) }));
    // Keep the total at 100% by adjusting the last other variation (two-variation case: the other one).
    if (variations.length === 2) next[1 - i].weight = 100000 - weight;
    onChange({ ...rollout, variations: next.filter((w) => w.weight > 0 || variations.length <= 2) });
  };
  return (
    <div className="rollout">
      <div className="rollout-bar" aria-hidden>
        {variations.map((_, i) => weightOf(i) > 0 && (
          <span key={i} style={{ width: `${weightOf(i) / 1000}%`, background: variationColor(i) }} title={pct(weightOf(i))} />
        ))}
      </div>
      {variations.map((_, i) => (
        <div key={i} className="rollout-row">
          <VariationName variations={variations} index={i} />
          <input type="range" min={0} max={100} step={1} value={weightOf(i) / 1000} onChange={(e) => setWeight(i, Number(e.target.value))} />
          <input type="number" className="pct" min={0} max={100} step={0.1} value={weightOf(i) / 1000}
            onChange={(e) => setWeight(i, Number(e.target.value))} /> %
        </div>
      ))}
      {total !== 100000 && <div className="error-box small">Weights add up to {pct(total)}; they must total 100%.</div>}
      <div className="rollout-opts">
        <label className="check" title="Records exposures and enables the results view">
          <input type="checkbox" checked={rollout.kind === "experiment"}
            onChange={(e) => onChange({ ...rollout, kind: e.target.checked ? "experiment" : "rollout" })} /> Run as experiment
        </label>
        <label className="inline">bucket by
          <input value={rollout.bucket_by ?? ""} placeholder="id" className="short"
            onChange={(e) => onChange({ ...rollout, bucket_by: e.target.value || undefined })} />
        </label>
      </div>
    </div>
  );
}
