/**
 * Demo store: the checkout page is behind the `new-checkout` flag.
 * Flip the flag (or edit its rules) in the dashboard and watch this page change, no reload.
 */
import { BrowserFlagClient, type User } from "../../sdks/typescript/src/browser.ts";
import "./style.css";

const CLIENT_ID = import.meta.env.VITE_CLIENT_ID as string | undefined;
const app = document.querySelector<HTMLDivElement>("#app")!;

if (!CLIENT_ID) {
  app.innerHTML = `<div class="setup"><h1>Demo not configured</h1>
    <p>Run <code>python scripts/seed_demo.py</code> from the repo root. It creates a demo org and
    flag and writes <code>demo-app/.env.local</code> with the client-side ID.</p></div>`;
  throw new Error("VITE_CLIENT_ID missing");
}

let user: User = { id: "user-2", country: "US", plan: "free" };
// Same origin: Vite proxies /sdk to the API.
const client = new BrowserFlagClient(CLIENT_ID, user, { baseUrl: window.location.origin });
let lastChange = 0;

client.onChange(() => {
  lastChange = performance.now();
  render();
});
void client.waitForInitialization(3000).then(render);

function render() {
  const detail = client.variationDetail<boolean>("new-checkout", false);
  const isNew = detail.value === true;
  const banner = client.string("promo-banner", "");
  app.innerHTML = `
    <header class="top">
      <span class="logo">🛍️ Demo Store</span>
      <span class="status ${client.isReady() ? "live" : ""}">${client.isReady() ? "● live" : "○ connecting…"}</span>
    </header>
    ${banner ? `<div class="promo">${escapeHtml(banner)}</div>` : ""}
    <section class="user">
      <h2>You are browsing as</h2>
      <div class="user-form">
        <label>User ID <input id="uid" value="${escapeHtml(user.id)}"></label>
        <label>Country <select id="country">${["US", "CA", "GB", "DE"].map((c) =>
          `<option ${c === user.country ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <label>Plan <select id="plan">${["free", "pro"].map((p) =>
          `<option ${p === user.plan ? "selected" : ""}>${p}</option>`).join("")}</select></label>
      </div>
      <p class="hint">Try a country of CA, or other user IDs (user-2 and user-4 fall in the 10% rollout).</p>
    </section>
    <section class="checkout ${isNew ? "new" : "old"}">
      ${isNew ? newCheckout() : oldCheckout()}
    </section>
    <footer class="why">
      <div><b>new-checkout</b> = <code>${JSON.stringify(detail.value)}</code></div>
      <div>reason: <code>${escapeHtml(JSON.stringify(detail.reason))}</code></div>
      ${lastChange ? `<div class="flash">updated live ${Math.round(performance.now() - lastChange)} ms ago</div>` : ""}
    </footer>`;
  for (const id of ["uid", "country", "plan"]) {
    document.getElementById(id)!.addEventListener("change", onUserChange);
  }
  document.getElementById("buy")?.addEventListener("click", () => {
    client.track("purchase", 49.99);
    const b = document.getElementById("buy")!;
    b.textContent = "Purchased ✓";
    b.setAttribute("disabled", "");
  });
}

function onUserChange() {
  user = {
    id: (document.getElementById("uid") as HTMLInputElement).value || "anonymous",
    country: (document.getElementById("country") as HTMLSelectElement).value,
    plan: (document.getElementById("plan") as HTMLSelectElement).value,
  };
  void client.identify(user).then(render);
}

const oldCheckout = () => `
  <h2>Checkout</h2>
  <ol class="steps"><li>Cart</li><li>Shipping</li><li>Billing</li><li>Review</li><li>Pay</li></ol>
  <div class="form-old">
    <p>Step 1 of 5: Review your cart</p>
    <div class="line"><span>Wireless headphones</span><span>$49.99</span></div>
    <button id="buy" class="old-btn">Continue to shipping →</button>
  </div>`;

const newCheckout = () => `
  <div class="badge">✨ New one-page checkout</div>
  <h2>Checkout</h2>
  <div class="grid">
    <div class="pane"><h3>Ship to</h3><div class="fake-input">1 Main St, Toronto</div><h3>Pay with</h3><div class="fake-input">•••• 4242</div></div>
    <div class="pane summary"><div class="line"><span>Wireless headphones</span><span>$49.99</span></div>
      <div class="line total"><span>Total</span><span>$49.99</span></div>
      <button id="buy" class="new-btn">Pay $49.99</button></div>
  </div>`;

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

setInterval(() => {
  const flash = document.querySelector(".flash");
  if (flash && lastChange) flash.textContent = `updated live ${((performance.now() - lastChange) / 1000).toFixed(0)} s ago`;
}, 1000);
