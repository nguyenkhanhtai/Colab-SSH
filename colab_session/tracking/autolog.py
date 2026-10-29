"""Zero-code automatic ML experiment logger and stdout metric scraper."""
import json
import re
from typing import Any, Dict, List, Optional

from colab_session.resources import render_template


class MetricParser:
    """Parses standard ML training metrics from stdout lines."""

    # Matches key: value or key=value, e.g. loss: 0.42, val_acc=0.88, lr: 1e-4
    KV_PATTERN = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_\-\/]*)\s*[:=]\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\b"
    )

    # Matches standalone metric names followed by number, e.g. 'loss 0.31'
    KEYWORD_PATTERN = re.compile(
        r"\b(epoch|step|loss|acc|accuracy|val_loss|val_acc|f1|precision|recall|lr)\s+([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\b",
        re.IGNORECASE,
    )

    # Matches 'Epoch 3/20' or 'Epoch: 3'
    EPOCH_PATTERN = re.compile(r"\bepoch\s*[:#]?\s*(\d+)(?:/(\d+))?\b", re.IGNORECASE)

    @classmethod
    def parse_line(cls, line: str) -> Dict[str, float]:
        """Extract all numeric metrics found in a single log line."""
        text = line.strip()
        if not text:
            return {}

        metrics: Dict[str, float] = {}

        # 1. Try parsing JSON format
        if text.startswith("{") and text.endswith("}"):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, (int, float)):
                            metrics[str(k).lower()] = float(v)
                    if metrics:
                        return metrics
            except Exception:
                pass

        # 2. Key-Value patterns (loss: 0.42, accuracy=0.91)
        for m in cls.KV_PATTERN.finditer(text):
            k = m.group(1).lower().replace("-", "_")
            try:
                metrics[k] = float(m.group(2))
            except ValueError:
                pass

        # 3. Keyword patterns (loss 0.42)
        for m in cls.KEYWORD_PATTERN.finditer(text):
            k = m.group(1).lower()
            try:
                metrics[k] = float(m.group(2))
            except ValueError:
                pass

        # 4. Epoch pattern
        m_ep = cls.EPOCH_PATTERN.search(text)
        if m_ep:
            metrics["epoch"] = float(m_ep.group(1))

        return metrics


class AutologScriptGenerator:
    """Generates the remote wrapper script to execute user command with zero-code tracking."""

    @staticmethod
    def generate_code(download_files: Optional[List[str]] = None) -> str:
        files_json = json.dumps(download_files or [])
        return render_template(
            "scripts",
            "wandb_autolog.py.template",
            context={"DOWNLOAD_FILES": files_json},
        )

