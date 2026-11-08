# Demo

**Browser demo:** a store whose checkout page is behind `new-checkout`, using the browser SDK.

```bash
python ../scripts/seed_demo.py    # creates a demo org + flags, writes .env.local
npm install && npm run dev        # http://localhost:5174
```

Toggle `new-checkout` (Development) in the dashboard, or change the user's country to CA, and
watch the page switch between the old 5-step and the new one-page checkout without reloading.
The footer shows the evaluation reason and how long ago the live update arrived.

**Terminal demo:** the Python SDK evaluating for four users, refreshed 4×/second.

```bash
python server_demo.py <server-key-printed-by-seed_demo>
```
