r"""
The model service: MedGemma in its own process, on this machine.

WHY IT EXISTS
The backend cannot hold this model. MedGemma 4B needs about 8 GB of RAM and
the backend already carries Whisper and Sortformer on a 15.8 GB machine.
Running it here keeps the two apart, so the backend starts in seconds and
stays the size it is today whether or not this service is running.

WHAT IT IS NOT
It is not a safety boundary. It returns the model's RAW text, ungated. The
grounding check runs in the backend (app/ml/grounding.gate_section), because
the backend owns the clinical record and this process does not. Do not add a
gate here: two gates in two processes is how the versions drift apart, and
the one that matters is the one nearest the record.

IT MUST STAY ON THIS MACHINE
Bound to 127.0.0.1 by default, which accepts connections from this computer
only. The project document states in 6.1 that every model runs on the same
machine as the backend and that no clinical text reaches a third party. That
is the supervisor's explicit instruction, not a preference. Exposing this
port, or tunnelling it, breaks it.

USAGE
    # terminal 1 -- the model (first start downloads ~8 GB, then loads)
    .\.venv\Scripts\python.exe -m scripts.llm_service --model google/medgemma-4b-it

    # terminal 2 -- the backend, told to use it
    #   set SOAP_ENGINE=remote and LLM_SERVICE_URL=http://127.0.0.1:8002
    #   in .env, then
    .\run_backend.ps1

Check it is alive:
    curl http://127.0.0.1:8002/health

Stop it with Ctrl+C. The backend keeps working without it -- notes fall back
to the verbatim rendering and the log says why.
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("llm_service")

SECTIONS = ("subjective", "objective", "assessment", "plan")


def _ensure_env() -> None:
    """
    Satisfy app.core.config without a .env file.

    This process touches no database, no auth and no encryption; it loads a
    model and generates text. The settings object nonetheless refuses to build
    without these, which is correct for the backend and unhelpful here. Only
    absent variables are filled, so a real .env always wins.

    ENCRYPTION_KEY is validated on load, so it cannot be arbitrary text: a
    Fernet key is exactly 32 bytes, base64url-encoded. The one below decodes
    to b"evaluation-only-not-a-real-key32" and encrypts nothing here.
    """
    placeholders = {
        "APP_ENV": "llm-service",
        "DATABASE_URL": "postgresql://unused/unused",
        "SIMULATED_EMR_URL": "http://localhost:8001",
        "JWT_SECRET": "unused-in-this-service",
        "ENCRYPTION_KEY": "ZXZhbHVhdGlvbi1vbmx5LW5vdC1hLXJlYWwta2V5MzI=",
    }
    for key, value in placeholders.items():
        os.environ.setdefault(key, value)


def build_app(model_id: str, dtype: str = None, max_new_tokens: int = None):
    from fastapi import FastAPI
    from pydantic import BaseModel
    from typing import Dict, List

    from app.core.config import settings
    settings.LLM_MODEL_ID = model_id
    if dtype:
        settings.LLM_DTYPE = dtype
    if max_new_tokens:
        settings.LLM_MAX_NEW_TOKENS = max_new_tokens
    # The gate lives in the backend. Switching it off here is not a weakening:
    # this process must return what the model actually said, so the backend
    # can judge it. See the module docstring.
    settings.LLM_GROUNDING_GATE = False

    from app.ml.llm_soap_engine import LLMSoapEngine, LLMSoapEngineError

    class RenderRequest(BaseModel):
        sections: Dict[str, List[str]]

    app = FastAPI(title="EMR Assistant — local SOAP model service")
    state = {"engine": None, "load_seconds": None}

    def engine():
        if state["engine"] is None:
            logger.info("loading %s ...", model_id)
            started = time.time()
            state["engine"] = LLMSoapEngine.get_instance()
            state["load_seconds"] = round(time.time() - started, 1)
            logger.info("loaded on %s as %s in %ss",
                        state["engine"].device, state["engine"].dtype,
                        state["load_seconds"])
        return state["engine"]

    @app.get("/health")
    def health():
        """Cheap. Does NOT load the model -- that is what /warmup is for."""
        return {
            "status": "ok",
            "model": model_id,
            "loaded": state["engine"] is not None,
            "load_seconds": state["load_seconds"],
        }

    @app.post("/warmup")
    def warmup():
        """
        Load the model now rather than on the first real note.

        Worth calling before a demo: otherwise the first consultation pays the
        load time on top of the generation time, and looks far slower than the
        system actually is.
        """
        try:
            eng = engine()
        except LLMSoapEngineError as e:
            return {"status": "failed", "error": str(e)}
        return {"status": "ok", "device": str(eng.device),
                "dtype": str(eng.dtype), "load_seconds": state["load_seconds"]}

    @app.post("/render")
    def render(request: RenderRequest):
        """
        Rewrite the selected sentences, one section at a time.

        A section that fails is omitted from the response rather than filled
        with anything invented. The backend treats a missing section as "use
        the verbatim text", so a partial answer still produces a whole note.
        """
        try:
            eng = engine()
        except LLMSoapEngineError as e:
            logger.error("model unavailable: %s", e)
            return {"sections": {}, "error": str(e)}

        out = {}
        timings = {}
        for name in SECTIONS:
            sentences = [s.strip() for s in (request.sections.get(name) or [])
                         if s and s.strip()]
            if not sentences:
                continue
            started = time.time()
            try:
                out[name] = eng._rewrite(name, sentences)
            except Exception as e:
                logger.error("rewriting %s failed (%s: %s)",
                             name, type(e).__name__, e)
                continue
            timings[name] = round(time.time() - started, 1)
            logger.info("%s: %d sentence(s) -> %ss",
                        name, len(sentences), timings[name])

        return {"sections": out, "seconds": timings}

    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="google/medgemma-4b-it")
    ap.add_argument("--host", default="127.0.0.1",
                    help="this machine only; see the module docstring before "
                         "changing it")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--dtype", default=None,
                    choices=("auto", "bfloat16", "float32"))
    ap.add_argument("--max-new-tokens", type=int, default=None)
    ap.add_argument("--warmup", action="store_true",
                    help="load the model at start instead of on first use")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)-8s %(name)s: %(message)s")
    _ensure_env()

    import uvicorn
    app = build_app(args.model, args.dtype, args.max_new_tokens)

    if args.warmup:
        from fastapi.testclient import TestClient
        print("loading the model before accepting requests ...", flush=True)
        print(TestClient(app).post("/warmup").json(), flush=True)

    print(f"\nserving {args.model} on http://{args.host}:{args.port}")
    print("set SOAP_ENGINE=remote and "
          f"LLM_SERVICE_URL=http://{args.host}:{args.port} in .env\n", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
