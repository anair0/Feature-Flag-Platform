import { AuditList } from "../components/AuditList";

export function AuditPage() {
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Audit log</h1>
          <p className="muted">Every change, who made it, and the exact before and after. Written in the same transaction as the change.</p></div>
      </header>
      <AuditList />
    </div>
  );
}
