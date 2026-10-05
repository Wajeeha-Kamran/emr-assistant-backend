"""
SOAP renderer that calls a model running in a separate local process.

WHY A SEPARATE PROCESS
MedGemma 4B needs roughly 8 GB of RAM. The backend already holds Whisper and
the Sortformer diarizer, and the development machine has 15.8 GB in total.
Loading the model inside the backend ran that machine out of memory. The model
therefore runs as its own service (scripts/llm_service.py) and the backend
asks it for text, exactly as the backend asks the simulated EMR service for a
sync -- a pattern the SDD already uses.

WHY THE ADDRESS IS A SETTING AND NOT A CONSTANT
So the service can be moved without touching this file. It must nonetheless
stay on this machine: the project document states, in section 6.1, that "all
three machine-learning models run on the same machine as the backend, so no
consultation audio or clinical text is ever sent to a third party service."
Pointing LLM_SERVICE_URL at a hosted notebook or any other remote host makes
that sentence false and breaks the supervisor's explicit instruction that
patient data must never reach an external API. Localhost only.

WHY THE GATE RUNS HERE AND NOT IN THE SERVICE
The service returns the model's raw text. The grounding check runs in this
process, which is the one that owns the clinical record. A gate inside the
service could be bypassed by restarting it with different settings, or by
pointing this engine at a different service; a gate here cannot. The remote
side is treated as an untrusted text generator, which is all it is.

WHAT HAPPENS WHEN IT IS NOT RUNNING
The note is still produced, as today's verbatim text, and the log says the
service was unreachable. A missing optional service must never cost a
consultation its note.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

SECTIONS = ("subjective", "objective", "assessment", "plan")


class RemoteSoapEngine:
    """Satisfies the SOAPEngine protocol in app/ml/soap_engine.py."""

    def __init__(self, url: str = None, timeout: float = None,
                 gate_enabled: bool = None, gate_threshold: float = None):
        from app.core.config import settings

        self.url = (url if url is not None
                    else settings.LLM_SERVICE_URL).rstrip("/")
        self.timeout = (timeout if timeout is not None
                        else settings.LLM_SERVICE_TIMEOUT_SECONDS)
        self.gate_enabled = (gate_enabled if gate_enabled is not None
                             else settings.LLM_GROUNDING_GATE)
        self.gate_threshold = (gate_threshold if gate_threshold is not None
                               else settings.LLM_GROUNDING_THRESHOLD)

        if not self.url:
            raise ValueError(
                "SOAP_ENGINE=remote needs LLM_SERVICE_URL, e.g. "
                "http://127.0.0.1:8002"
            )
        self._warn_if_not_local()

    def _warn_if_not_local(self) -> None:
        """
        Say so, loudly, if the address is not on this machine.

        Not an exception: a deployment on a hospital's own network is a
        legitimate future configuration, and this code cannot tell that apart
        from a tunnel to a notebook. But it is the kind of change that must
        never happen by accident, so it is stated at WARNING on every start.
        """
        from urllib.parse import urlparse

        host = (urlparse(self.url).hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
            logger.warning(
                "LLM_SERVICE_URL points at %r, which is not this machine. "
                "Clinical text will leave this host. The project document "
                "(6.1) states that no consultation audio or clinical text is "
                "ever sent to a third party service; that claim no longer "
                "holds with this setting.", host,
            )

    # ------------------------------------------------------------------

    def render(self, sections: Dict[str, List[str]]) -> Dict[str, str]:
        from app.services.soap_service import fallback_for

        picked = {name: [s.strip() for s in (sections.get(name) or []) if s.strip()]
                  for name in SECTIONS}
        wanted = {name: sents for name, sents in picked.items() if sents}

        out: Dict[str, str] = {}
        for name in SECTIONS:
            if not picked[name]:
                out[name] = fallback_for(name)

        if not wanted:
            return out

        generated = self._ask(wanted)

        for name, sents in wanted.items():
            text = (generated or {}).get(name)
            if not text or not str(text).strip():
                # No usable text for this section: either the service is down,
                # or it returned nothing for it. Either way the note is still
                # produced from the sentences that were actually spoken.
                out[name] = self._verbatim(name, sents)
                continue
            out[name] = self._gate(name, sents, str(text).strip())
        return out

    def _ask(self, wanted: Dict[str, List[str]]) -> Dict[str, str]:
        """
        One request for the whole note. Returns {} on any failure.

        Every failure is the same failure from here: no text. The log
        distinguishes them so a reader can tell "the service is not running"
        from "the service is running and broke", which need different fixes.
        """
        import httpx

        try:
            response = httpx.post(
                f"{self.url}/render",
                json={"sections": wanted},
                timeout=self.timeout,
            )
        except httpx.ConnectError:
            logger.warning(
                "LLM service at %s is not reachable; the note falls back to "
                "the verbatim rendering. Start it with "
                "'python -m scripts.llm_service', or set SOAP_ENGINE="
                "extractive to stop trying.", self.url,
            )
            return {}
        except httpx.TimeoutException:
            logger.warning(
                "LLM service at %s did not answer within %ss; the note falls "
                "back to the verbatim rendering. On CPU a 4B model can take "
                "minutes per section -- raise LLM_SERVICE_TIMEOUT_SECONDS if "
                "that is expected here.", self.url, self.timeout,
            )
            return {}
        except Exception as e:
            logger.warning("LLM service call failed (%s: %s); falling back.",
                           type(e).__name__, e)
            return {}

        if response.status_code != 200:
            logger.warning("LLM service returned %s: %s",
                           response.status_code, response.text[:300])
            return {}

        try:
            body = response.json()
        except Exception:
            logger.warning("LLM service returned a non-JSON body; falling back.")
            return {}

        generated = body.get("sections")
        if not isinstance(generated, dict):
            logger.warning(
                "LLM service response has no 'sections' object; falling back.")
            return {}
        return generated

    def _gate(self, section: str, sentences: List[str], text: str) -> str:
        if not self.gate_enabled:
            return text
        from app.ml.grounding import gate_section
        return gate_section(section, sentences, text, self.gate_threshold)

    @staticmethod
    def _verbatim(section: str, sentences: List[str]) -> str:
        from app.services.soap_service import SOAPService
        return SOAPService.render_extractive({section: sentences})[section]
