from fastapi import FastAPI

app = FastAPI(
    title="CEQ Platform",
    version="1.0.0"
)

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "ceq-platform"
    }
