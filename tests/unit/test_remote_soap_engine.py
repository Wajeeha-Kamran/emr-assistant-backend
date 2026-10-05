"""
The renderer that calls the model service.

No model, no service, no network: httpx.post is replaced so every failure the
service can present is exercised deliberately. What is being tested is the
promise this engine makes -- a note is always produced, the gate always runs
here, and nothing the service returns is trusted.
"""

from app.ml.remote_soap_engine import RemoteSoapEngine


SOURCE = {
    "objective": [
        "Your blood pressure today is one thirty two over eighty four.",
        "Your HbA1c has come back at fifty eight millimoles per mole.",
    ],
}


def _engine(monkeypatch, responder):
    """A RemoteSoapEngine whose HTTP call is REPLACED by responder()."""
    import httpx
    monkeypatch.setattr(httpx, "post", responder)
    return RemoteSoapEngine(url="http://127.0.0.1:8002", timeout=1.0,
                            gate_enabled=True, gate_threshold=0.5)


class _Response:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_a_faithful_rewrite_is_returned(monkeypatch):
    prose = ("Blood pressure is 132/84. HbA1c has come back at 58 mmol/mol.")
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response({"sections": {"objective": prose}}))
    out = engine.render(SOURCE)
    assert out["objective"] == prose


def test_sections_with_no_sentences_get_their_empty_line(monkeypatch):
    """A section nobody spoke about must still say so, not come back blank."""
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response({"sections": {"objective": "BP is 132/84."}}))
    out = engine.render(SOURCE)
    for name in ("subjective", "assessment", "plan"):
        assert out[name], f"{name} is empty"


# ---------------------------------------------------------------------------
# The gate runs HERE, not in the service
# ---------------------------------------------------------------------------

def test_a_wrong_number_from_the_service_is_rejected(monkeypatch):
    """
    The service is an untrusted text generator.

    This is the tenfold HbA1c error arriving over HTTP instead of from an
    in-process model. It must be caught in exactly the same way, because the
    check lives in this process and not in the one that produced the text.
    """
    bad = "Blood pressure is 132/84. The HbA1c is 5.8 mmol/mol."
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response({"sections": {"objective": bad}}))
    out = engine.render(SOURCE)
    assert "5.8" not in out["objective"]
    assert "fifty eight millimoles per mole" in out["objective"]


def test_an_invented_sentence_from_the_service_is_rejected(monkeypatch):
    invented = "The patient denies any other symptoms."
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response({"sections": {"objective": invented}}))
    out = engine.render(SOURCE)
    assert "denies" not in out["objective"]


# ---------------------------------------------------------------------------
# Every way the service can let us down
# ---------------------------------------------------------------------------

def _verbatim_came_back(out):
    return "fifty eight millimoles per mole" in out["objective"]


def test_service_not_running(monkeypatch):
    import httpx

    def refuse(*a, **k):
        raise httpx.ConnectError("connection refused")

    assert _verbatim_came_back(_engine(monkeypatch, refuse).render(SOURCE))


def test_service_too_slow(monkeypatch):
    import httpx

    def stall(*a, **k):
        raise httpx.ReadTimeout("too slow")

    assert _verbatim_came_back(_engine(monkeypatch, stall).render(SOURCE))


def test_service_returns_an_error_status(monkeypatch):
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response(None, 500, "boom"))
    assert _verbatim_came_back(engine.render(SOURCE))


def test_service_returns_junk(monkeypatch):
    engine = _engine(monkeypatch, lambda *a, **k: _Response(None, 200, "<html>"))
    assert _verbatim_came_back(engine.render(SOURCE))


def test_service_omits_the_section(monkeypatch):
    """A partial answer still produces a whole note."""
    engine = _engine(monkeypatch, lambda *a, **k: _Response({"sections": {}}))
    assert _verbatim_came_back(engine.render(SOURCE))


def test_service_returns_an_empty_string(monkeypatch):
    engine = _engine(monkeypatch,
                     lambda *a, **k: _Response({"sections": {"objective": "   "}}))
    assert _verbatim_came_back(engine.render(SOURCE))


def test_service_raises_something_unexpected(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("something nobody predicted")

    assert _verbatim_came_back(_engine(monkeypatch, explode).render(SOURCE))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_an_empty_url_is_refused():
    """Failing at construction beats failing silently on every consultation."""
    try:
        RemoteSoapEngine(url="", timeout=1.0)
    except ValueError as e:
        assert "LLM_SERVICE_URL" in str(e)
    else:
        raise AssertionError("an empty URL should not be accepted")


def test_a_non_local_address_is_warned_about(caplog):
    """
    Project document 6.1 claims no clinical text leaves this machine.

    A remote address makes that false, so it cannot pass silently. It is a
    warning rather than an error because a hospital's own network is a
    legitimate future deployment and this code cannot tell the difference.
    """
    import logging
    with caplog.at_level(logging.WARNING):
        RemoteSoapEngine(url="https://example.ngrok.io", timeout=1.0)
    assert any("not this machine" in r.getMessage() for r in caplog.records)


def test_a_local_address_is_not_warned_about(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        RemoteSoapEngine(url="http://127.0.0.1:8002", timeout=1.0)
    assert not any("not this machine" in r.getMessage()
                   for r in caplog.records)


# ---------------------------------------------------------------------------
# The factory
# ---------------------------------------------------------------------------

def test_the_factory_returns_this_engine_for_remote(monkeypatch):
    """
    SOAP_ENGINE=remote must select it WITHOUT loading a model or opening a
    connection. The backend has to start whether or not the model service
    happens to be running.
    """
    from app.core import config as config_module
    from app.ml import soap_engine as factory

    monkeypatch.setattr(config_module.settings, "SOAP_ENGINE", "remote")
    factory.reset_engine()
    try:
        engine = factory.get_soap_engine()
        assert isinstance(engine, RemoteSoapEngine)
    finally:
        factory.reset_engine()


def test_the_default_engine_is_still_extractive():
    """
    The shipped behaviour. Project document 6.1 states the pipeline "is
    extractive rather than generative"; that sentence stays true only while
    this is the default, so it is asserted rather than assumed.
    """
    from app.core.config import settings
    assert settings.SOAP_ENGINE == "extractive"


def test_an_unknown_engine_name_is_refused(monkeypatch):
    from app.core import config as config_module
    from app.ml import soap_engine as factory

    monkeypatch.setattr(config_module.settings, "SOAP_ENGINE", "medgemma")
    factory.reset_engine()
    try:
        factory.get_soap_engine()
    except factory.SOAPEngineError as e:
        assert "remote" in str(e)
    else:
        raise AssertionError("an unknown engine name should be refused")
    finally:
        factory.reset_engine()
