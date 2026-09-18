from __future__ import annotations

import argparse
import json
from pathlib import Path

from .assistant import CourseAssistant
from .ingest import ingest_file
from .services import ClassServiceClient, ServiceSettings


def load_assistant(paths: list[str]) -> CourseAssistant:
    chunks = []
    for path in paths:
        chunks.extend(ingest_file(path))
    if not chunks:
        raise ValueError("no readable text was found in the supplied materials")
    settings = ServiceSettings.from_env()
    client = ClassServiceClient(settings) if settings.api_key and settings.api_key != "replace-with-local-dummy-value" else None
    if client:
        try:
            return CourseAssistant.from_chunks(chunks, service_client=client)
        except RuntimeError:
            pass
    return CourseAssistant.from_chunks(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask questions of course materials")
    parser.add_argument("files", nargs="+", help="PDF, PPTX, DOCX, TXT, or Markdown course files")
    parser.add_argument("--question", required=True)
    parser.add_argument("--material")
    parser.add_argument("--topic")
    args = parser.parse_args()
    assistant = load_assistant(args.files)
    print(json.dumps(assistant.ask(args.question, args.material, args.topic).as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
