"""JSON logs. Fields that could carry document text or questions are dropped, whatever the caller passes."""
import json
import logging
import sys
import time

DROPPED = {"text", "question", "content", "answer", "prompt", "messages", "passage", "query"}
STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)), "level": record.levelname,
               "service": self.service, "logger": record.name, "message": record.getMessage()}
        for key, value in vars(record).items():
            if key not in STANDARD and key not in DROPPED and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(out, default=str)


def configure(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("uvicorn.access").setLevel("WARNING")
