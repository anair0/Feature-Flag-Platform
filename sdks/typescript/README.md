# @flagplatform/sdk (TypeScript)

Two clients, one package, no runtime dependencies.

## Node (server-side, local evaluation)

```ts
import { FlagClient } from "@flagplatform/sdk";

const client = await FlagClient.init("srv-...", { baseUrl: "https://flags.example.com" }); // never rejects

const user = { id: "user-123", country: "CA" };
if (client.bool("new-checkout", user, false)) { /* ... */ }
client.variationDetail("new-checkout", user, false).reason; // why
client.track(user, "purchase", 49.99);
client.onChange((key) => console.log(key, "changed"));
await client.close();
```

## Browser (remote evaluation)

Browsers never receive rules: the server evaluates and returns only values of flags marked
"client-side". The client-side ID is public.

```ts
import { BrowserFlagClient } from "@flagplatform/sdk/browser";

const flags = new BrowserFlagClient("cli-...", { id: "user-123", country: "CA" }, { baseUrl: "https://flags.example.com" });
await flags.waitForInitialization();
flags.bool("new-checkout", false);
flags.onChange(() => rerender());   // fires when a teammate edits the flag
await flags.identify({ id: "user-456" }); // after login
```

Both clients never throw, take a default on every read, and keep serving last known values
when the server is unreachable.

```bash
npm install && npm test && npm run build
```
