# Class model services

The supplied class endpoints currently use plain HTTP. The adapter refuses HTTP unless `CLASS_SERVICE_ALLOW_INSECURE_HTTP=true` is explicitly set. Only enable that flag on the trusted class network; use HTTPS for production whenever available. The API key remains server-side and is intentionally absent from this repository.

All service clients must use the vLLM 0.29.0-compatible request conventions and model-specific Hugging Face templates. Do not infer a request shape from the port alone; keep each adapter explicit and test it against the live service.

| Role | Port | Model | Endpoint |
|---|---:|---|---|
| Text embeddings | 9002 | `nvidia/Nemotron-3-Embed-1B-BF16` | `http://dobolyi.com:9002/v2/embed` |
| Visual/multimodal embeddings | 9003 | `Qwen/Qwen3-VL-Embedding-2B` | `http://dobolyi.com:9003/v1/embeddings` |
| Multimodal reranking | 9004 | `Qwen/Qwen3-VL-Reranker-2B` | `http://dobolyi.com:9004/rerank` |
| Document parsing | 9005 | `dots.mocr` | `http://dobolyi.com:9005/v1/chat/completions` |

## Request notes confirmed during connectivity checks

- **Text embeddings:** the class endpoint requires a non-empty `texts` field, for example `{"model":"nvidia/Nemotron-3-Embed-1B-BF16","texts":["..."]}`. The OpenAI-style `input` field is rejected by this service-specific `/v2/embed` adapter. The model card recommends query/passage prefixes for retrieval and documents a 2048-dimensional output.
- **Visual embeddings:** use the OpenAI-compatible embeddings shape with `model` and `input`; multimodal inputs must follow the Qwen3-VL content format from the model card.
- **Reranking:** send a query and candidate documents using the service's rerank contract. Candidate documents may contain text and/or visual content; the Qwen model card documents the multimodal pair structure.
- **Document parsing:** use chat-completions messages. `dots.mocr` supports multimodal content, including an image item and a text instruction, and is intended to preserve layout and structured graphics.

Connectivity was checked with a harmless probe for each endpoint using the supplied class credential. The corrected text-embedding request and the visual embedding, reranker, and parser probes returned HTTP 200 responses. The initial text request using `input` returned HTTP 400 with a validation message requiring `texts`; this behavior is captured above so the eventual adapter does not repeat that mistake.

## References

- [Nemotron-3-Embed-1B-BF16 model card](https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16)
- [Qwen3-VL-Embedding-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)
- [Qwen3-VL-Reranker-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Reranker-2B)
- [dots.mocr model card](https://huggingface.co/dots-studio/dots.mocr)
- [vLLM 0.29.0 documentation](https://docs.vllm.ai/en/v0.29.0/)
- [vLLM 0.29.0 scoring usage](https://docs.vllm.ai/en/v0.29.0/models/pooling_models/scoring/)
- [vLLM 0.29.0 classification usage](https://docs.vllm.ai/en/v0.29.0/models/pooling_models/classify/)
