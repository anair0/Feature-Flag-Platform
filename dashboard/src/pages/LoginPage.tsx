import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, tokenStore } from "../api/client";
import { ErrorBox } from "../components/ui";

export function LoginPage({ mode }: { mode: "login" | "signup" }) {
  const [form, setForm] = useState({ email: "", password: "", name: "", org_name: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = useMutation({
    mutationFn: () => (mode === "login" ? api.login(form.email, form.password) : api.signup(form)),
    onSuccess: ({ token }) => {
      tokenStore.set(token);
      window.location.assign("/");
    },
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); submit.mutate(); };

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={onSubmit}>
        <div className="brand big"><span className="logo" aria-hidden>⚑</span> Flagship</div>
        <h1>{mode === "login" ? "Sign in" : "Create your organization"}</h1>
        {mode === "signup" && (
          <>
            <label>Your name<input required value={form.name} onChange={set("name")} autoComplete="name" /></label>
            <label>Organization<input required value={form.org_name} onChange={set("org_name")} placeholder="Acme Inc." /></label>
          </>
        )}
        <label>Email<input required type="email" value={form.email} onChange={set("email")} autoComplete="email" /></label>
        <label>Password
          <input required type="password" minLength={mode === "signup" ? 8 : undefined} value={form.password}
            onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>
        <ErrorBox error={submit.error} />
        <button className="primary" disabled={submit.isPending}>
          {submit.isPending ? "…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <p className="muted small">
          {mode === "login"
            ? <>New here? <Link to="/signup">Create an organization</Link></>
            : <>Have an account? <Link to="/login">Sign in</Link></>}
        </p>
      </form>
    </div>
  );
}
