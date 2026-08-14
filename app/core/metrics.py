from typing import Dict
from threading import Lock

class PipelineMetrics:
    def __init__(self):
        self._lock = Lock()
        self._metrics = {
            "asr": {"success": 0, "failure": 0},
            "diarization": {"success": 0, "failure": 0},
            "soap_generation": {"success": 0, "failure": 0},
            "code_suggestion": {"success": 0, "failure": 0},
            "emr_sync": {"success": 0, "failure": 0},
            "retention": {"success": 0, "failure": 0},
        }

    def record_metric(self, stage: str, success: bool):
        if stage not in self._metrics:
            return
        with self._lock:
            if success:
                self._metrics[stage]["success"] += 1
            else:
                self._metrics[stage]["failure"] += 1

    def get_metrics(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            # Return a shallow copy of the inner dicts to prevent race conditions during serialization
            return {k: v.copy() for k, v in self._metrics.items()}

# Global singleton
metrics = PipelineMetrics()
