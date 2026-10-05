# Class model services

The supplied class services use plain HTTP. The client rejects HTTP unless `CLASS_SERVICE_ALLOW_INSECURE_HTTP=true` is explicitly set. Enable that only on the trusted class network; use HTTPS in production whenever available. The API key is server-side only and is intentionally absent from this repository.

Port 9000 is reserved for Hermes agentic use and is not used by this application. The course assistant integrates ports 9001–9005. Ports 9006–9010 are recorded as adjacent class capabilities but are not required for the course-assistant workflow.

## Integrated course-assistant services

| Role | Port | Model | Default endpoint | App use |
|---|---:|---|---|---|
| Vision-capable answer/classification LLM | 9001 | `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` | `http://dobolyi.com:9001/v1/chat/completions` | Grounded answer synthesis and visual explanation |
| Text embeddings | 9002 | `nvidia/Nemotron-3-Embed-1B-BF16` | `http://dobolyi.com:9002/v2/embed` | Text-vector retrieval; send `texts` |
| Multimodal embeddings | 9003 | `Qwen/Qwen3-VL-Embedding-2B` | `http://dobolyi.com:9003/v1/embeddings` | Text/image retrieval |
| Multimodal reranking | 9004 | `Qwen/Qwen3-VL-Reranker-2B` | `http://dobolyi.com:9004/rerank` | Candidate relevance scoring |
| Document parsing | 9005 | `dots.mocr` | `http://dobolyi.com:9005/v1/chat/completions` | Fallback text and layout reading for slide images |

All default hosts and paths are configurable through environment variables in `.env.example`; no credential value is committed.

## Additional class capabilities not required by this app

| Port | Capability | Model | Current status |
|---:|---|---|---|
| 9006 | Image generation/editing | `black-forest-labs/FLUX.2-klein-4B` | Not called by the course assistant; generated images are not evidence |
| 9007 | Music generation | `ACE-Step/acestep-v15-xl-turbo` | Not relevant to course QA/quiz workflows |
| 9008 | Text-to-speech/voice cloning | Chatterbox Multilingual V3 | Not required; avoid sending student/course content without consent |
| 9009 | Speech-to-text | `openai/whisper-large-v3-turbo` | Not required because the UI accepts files and text |
| 9010 | Structured decisions | `internlm/Intern-Decision-4B` | Optional future quiz/triage experiments; not used for answer keys |

## Request contracts

- **9001 vision answer LLM:** OpenAI-compatible chat-completions payload with a text instruction, grounded excerpts, and optional `image_url` data URLs. The answer prompt explicitly forbids unsupported claims and asks the model to rely only on supplied evidence. Thinking is turned off with a top-level `"chat_template_kwargs": {"enable_thinking": false}` field (not inside `extra_body`, which is an OpenAI SDK argument that the raw HTTP API ignores). The same model writes the short slide descriptions shown with visual evidence.
- **9002 text embeddings:** service-specific payload with `model` and non-empty `texts`; query and passage prefixes are used by the retriever. The reply nests the vectors as `{"embeddings": {"float": [[...], ...]}}`. Requests are sent in batches of 32.
- **9003 multimodal embeddings:** a text query is sent as `{"model": ..., "input": "<text>"}`. A slide image is sent one per request as `{"model": ..., "messages": [{"role": "user", "content": [{"type": "image_url", ...}, {"type": "text", ...}]}]}`. The reply is `data[0].embedding`. A list of image objects in `input` is rejected by the service.
- **9004 reranking:** payload with `model`, `query`, and `documents`, where each document is either a plain string or `{"content": [{"type": "image_url", ...}, {"type": "text", ...}]}`. The reply is `results[]` with `index` and `relevance_score`; scores are matched to documents by `index`.
- **9005 document parsing:** chat-completions messages containing an image item and an instruction. It is an OCR model, so the app uses it as the fallback for slide descriptions when the 9001 vision model is unavailable.
- **9010 structured decisions:** if used in a future feature, send its custom `state`/`questions`/`images` schema, not chat-completions messages.

These formats were confirmed against the live services on 2026-10-05 and are locked in by `tests/test_class_service_contracts.py`. Embeddings and slide descriptions are cached in memory by content, so each slide is sent to the services once per app session.

The application falls back to local extractive answers and keyword retrieval when optional class services are unavailable. Remote calls are not required for the dependency-light test suite.

## References

- [Qwen3.6 vision model card](https://huggingface.co/cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit)
- [Nemotron-3-Embed-1B-BF16 model card](https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16)
- [Qwen3-VL-Embedding-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)
- [Qwen3-VL-Reranker-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Reranker-2B)
- [dots.mocr model card](https://huggingface.co/dots-studio/dots.mocr)
- [FLUX.2-klein-4B model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
- [ACE-Step API documentation](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md)
- [Chatterbox API documentation](http://dobolyi.com:9008/docs)
- [Intern-Decision API documentation](http://dobolyi.com:9010/docs)
- [vLLM documentation](https://docs.vllm.ai/en/latest/)
