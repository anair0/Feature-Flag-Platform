from fastapi import FastAPI

app = FastAPI(title="Feature Flag Platform")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
