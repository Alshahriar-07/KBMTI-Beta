"""In-process llama.cpp inference engine (Vulkan or CPU), driven through the ctypes shim.

Nothing in this module spawns a process or opens a socket: the GGUF model is decoded by
``llama.dll`` inside the calling Python process, which is what keeps KIE embedded in the
KBMTI backend rather than next to it.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .bindings import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_WARN,
    LlamaApi,
    LlamaLoadError,
    LogCapture,
)

DEFAULT_N_CTX = 8192


class ModelNotLoadedError(RuntimeError):
    """Raised when generation is attempted before a successful load."""


class PromptTooLongError(RuntimeError):
    """Raised when the rendered prompt does not fit the context budget."""


class GenerationCancelled(RuntimeError):
    """Raised internally when the cancel flag is observed during decoding."""


@dataclass
class LoadReport:
    model_path: str
    runtime_dir: str
    requested_gpu_layers: int
    load_seconds: float
    backend_log: list[str]
    backend: dict[str, object] = field(default_factory=dict)
    model: dict[str, object] = field(default_factory=dict)
    context: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GenerationReport:
    text: str
    prompt_tokens: int
    generated_tokens: int
    ttft_ms: float
    prompt_ms: float
    decode_ms: float
    total_ms: float
    prompt_tok_per_s: float
    decode_tok_per_s: float
    finish: str  # "eog" | "length" | "cancelled" | "aborted"
    cancelled: bool = False
    prompt_truncated_tokens: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "prompt_tokens": self.prompt_tokens,
            "generated_tokens": self.generated_tokens,
            "ttft_ms": round(self.ttft_ms, 2),
            "prompt_ms": round(self.prompt_ms, 2),
            "decode_ms": round(self.decode_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "prompt_tok_per_s": round(self.prompt_tok_per_s, 2),
            "decode_tok_per_s": round(self.decode_tok_per_s, 2),
            "finish": self.finish,
            "cancelled": self.cancelled,
            "prompt_truncated_tokens": self.prompt_truncated_tokens,
        }


class LlamaRuntime:
    """Single-model, single-context engine. One instance per process."""

    def __init__(
        self,
        model_path: str | Path,
        runtime_dir: str | Path,
        *,
        n_gpu_layers: int = 99,
        n_ctx: int = DEFAULT_N_CTX,
        n_batch: int = 512,
        n_ubatch: int = 512,
        n_threads: int | None = None,
        seed: int = 1234,
    ) -> None:
        self.model_path = Path(model_path)
        self.runtime_dir = Path(runtime_dir)
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.n_batch = n_batch
        self.n_ubatch = n_ubatch
        self.n_threads = n_threads or max(1, (os.cpu_count() or 4) - 1)
        self.seed = seed

        self._api: LlamaApi | None = None
        self._model: int | None = None
        self._ctx: int | None = None
        self._vocab: int | None = None
        self._template: str | None = None
        self._lock = threading.Lock()
        self.log = LogCapture()
        self._backend_initialised = False
        self._backend_report: dict[str, object] = {}

    # -- lifecycle -------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._model is not None and self._ctx is not None

    def load(self) -> LoadReport:
        with self._lock:
            if self.loaded:
                raise RuntimeError("model already loaded; unload() first")
            if not self.model_path.is_file():
                raise LlamaLoadError(f"model file not found: {self.model_path}")

            started = time.perf_counter()
            api = LlamaApi(self.runtime_dir, log=self.log)
            self._api = api
            if not self._backend_initialised:
                api.backend_init()
                self._backend_report = api.load_backends(self.runtime_dir)
                self._backend_initialised = True

            params = api.model_default_params()
            params.n_gpu_layers = self.n_gpu_layers
            params.use_extra_bufts = True
            model = api.lib.llama_model_load_from_file(str(self.model_path).encode(), params)
            if not model:
                raise LlamaLoadError(
                    "llama_model_load_from_file returned NULL; see backend_log for ggml/llama errors"
                )
            self._model = model

            cparams = api.context_default_params()
            cparams.n_ctx = self.n_ctx
            cparams.n_batch = self.n_batch
            cparams.n_ubatch = min(self.n_ubatch, self.n_batch)
            cparams.n_threads = self.n_threads
            cparams.n_threads_batch = self.n_threads
            cparams.offload_kqv = True
            ctx = api.lib.llama_init_from_model(model, cparams)
            if not ctx:
                api.lib.llama_model_free(model)
                self._model = None
                raise LlamaLoadError("llama_init_from_model returned NULL (context/VRAM allocation failed)")
            self._ctx = ctx
            self._vocab = api.lib.llama_model_get_vocab(model)

            raw_template = api.lib.llama_model_chat_template(model, None)
            self._template = raw_template.decode("utf-8", "replace") if raw_template else None

            elapsed = time.perf_counter() - started
            backend_log = [line for _lvl, line in self.log.snapshot()]
            warnings = [
                line
                for lvl, line in self.log.snapshot()
                if lvl in (LOG_LEVEL_WARN, LOG_LEVEL_ERROR) and "ggml_vulkan" not in line
            ]
            model_info = {
                "description": api.model_desc(model),
                "n_layer": api.lib.llama_model_n_layer(model),
                "n_ctx_train": api.lib.llama_model_n_ctx_train(model),
                "n_embd": api.lib.llama_model_n_embd(model),
                "n_head": api.lib.llama_model_n_head(model),
                "n_head_kv": api.lib.llama_model_n_head_kv(model),
                "n_params": api.lib.llama_model_n_params(model),
                "size_bytes": api.lib.llama_model_size(model),
                "n_vocab": api.lib.llama_vocab_n_tokens(self._vocab),
                "quantization": api.model_meta(model, "general.file_type"),
                "architecture": api.model_meta(model, "general.architecture"),
                "chat_template": (self._template[:80] + "...") if self._template else None,
            }
            ctx_info = {
                "n_ctx": api.lib.llama_n_ctx(ctx),
                "n_batch": api.lib.llama_n_batch(ctx),
                "n_ubatch": api.lib.llama_n_ubatch(ctx),
                "n_threads": cparams.n_threads,
            }
            return LoadReport(
                model_path=str(self.model_path),
                runtime_dir=str(self.runtime_dir),
                requested_gpu_layers=self.n_gpu_layers,
                load_seconds=elapsed,
                backend_log=backend_log,
                backend=dict(self._backend_report),
                model=model_info,
                context=ctx_info,
                warnings=warnings,
            )

    def unload(self) -> None:
        with self._lock:
            api = self._api
            if api is None:
                return
            if self._ctx:
                api.lib.llama_free(self._ctx)
                self._ctx = None
            if self._model:
                api.lib.llama_model_free(self._model)
                self._model = None
            self._vocab = None
            self._template = None

    def shutdown(self) -> None:
        self.unload()
        if self._api is not None and self._backend_initialised:
            self._api.backend_free()
            self._backend_initialised = False

    # -- introspection ---------------------------------------------------
    def abi(self) -> dict[str, object]:
        return self._api.describe_abi() if self._api else {}

    def backend_identity(self) -> dict[str, object]:
        """What ggml actually initialised: device names, layer offload lines, GPU support."""
        if self._api is None:
            return {}
        lines = [line for _lvl, line in self.log.snapshot()]
        devices = [line for line in lines if "ggml_vulkan: " in line and "=" in line]
        offload = [line for line in lines if "offload" in line.lower() or "buffer size" in line.lower()]
        return {
            "runtime_tag": self._api.describe_abi().get("runtime_tag"),
            "llama_version": self._api.version(),
            "supports_gpu_offload": bool(self._backend_report.get("gpu_device_present")),
            "backend_load": dict(self._backend_report),
            "vulkan_devices": devices,
            "offload_lines": offload,
        }

    # -- generation ------------------------------------------------------
    def render_chat(self, messages: list[dict[str, str]], add_assistant: bool = True) -> str:
        if self._api is None or self._template is None:
            raise ModelNotLoadedError("no chat template available; model not loaded")
        pairs = [(m["role"], m["content"]) for m in messages]
        return self._api.apply_chat_template(self._template, pairs, add_assistant)

    @staticmethod
    def apply_thinking_switch(messages: list[dict[str, str]], thinking: bool) -> list[dict[str, str]]:
        """Qwen3 hybrid thinking is controlled by the ``/no_think`` soft switch.

        The GGUF chat template does not expose ``enable_thinking`` through the C API at
        this tag, so fast mode appends the documented soft switch to the system prompt.
        The model still emits a (usually empty) thinking block, which the caller can hide.
        """
        prepared = [dict(message) for message in messages]
        if thinking:
            return prepared
        if prepared and prepared[0].get("role") == "system":
            prepared[0]["content"] = prepared[0]["content"].rstrip() + "\n/no_think"
        else:
            prepared.insert(0, {"role": "system", "content": "/no_think"})
        return prepared

    @staticmethod
    def strip_empty_thinking(text: str) -> str:
        """Remove a leading thinking block that holds no reasoning.

        In fast mode Qwen3 still emits an empty block (7 tokens here, rendered as
        ``<think>\n\n</think>`` by this GGUF's template); the text is identical without it,
        so callers get clean output while the token counts keep telling the truth about
        what the model actually produced.
        """
        for close_tag in ("</think>", "</think>"):
            end = text.find(close_tag)
            if end == -1:
                continue
            if text[:end].strip() not in ("<think>", " thinking", "thinking"):
                continue
            return text[end + len(close_tag) :].lstrip()
        return text

    def count_tokens(self, text: str) -> int:
        if self._api is None or self._vocab is None:
            raise ModelNotLoadedError("model not loaded")
        return len(self._api.tokenize(self._vocab, text, add_special=False, parse_special=True))

    def generate(
        self,
        messages: list[dict[str, str]] | None = None,
        *,
        prompt: str | None = None,
        max_tokens: int = 128,
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: int = 20,
        repeat_penalty: float = 1.05,
        thinking: bool = False,
        cancel_event: threading.Event | None = None,
        on_token=None,
    ) -> GenerationReport:
        api = self._api
        if api is None or self._ctx is None or self._vocab is None or self._model is None:
            raise ModelNotLoadedError("model not loaded")
        if prompt is None:
            if messages is None:
                raise ValueError("either messages or prompt is required")
            prompt = self.render_chat(self.apply_thinking_switch(messages, thinking))

        tokens = api.tokenize(self._vocab, prompt, add_special=True, parse_special=True)
        n_ctx = int(api.lib.llama_n_ctx(self._ctx))
        budget = n_ctx - max_tokens
        truncated = 0
        if len(tokens) > budget:
            # Keep the tail: the last messages carry the user turn.
            truncated = len(tokens) - budget
            tokens = tokens[truncated:]
        if not tokens:
            raise PromptTooLongError(f"prompt does not fit: {n_ctx} ctx, {max_tokens} reserved for output")

        cancel = cancel_event or threading.Event()
        cancelled = False

        def _abort(_data) -> bool:
            return cancel.is_set()

        api.set_abort_callback(self._ctx, _abort)

        chain = api.lib.llama_sampler_chain_init(api.sampler_chain_default_params())
        if temperature <= 0.0:
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_greedy())
        else:
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_penalties(
                int(api.lib.llama_vocab_n_tokens(self._vocab)), 64, repeat_penalty, 0.0, 0.0
            ))
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_top_k(top_k))
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_top_p(top_p, 1))
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_temp(temperature))
            api.lib.llama_sampler_chain_add(chain, api.lib.llama_sampler_init_dist(self.seed))

        started = time.perf_counter()
        pieces: list[str] = []
        generated = 0
        ttft_ms = 0.0
        prompt_ms = 0.0
        decode_ms = 0.0
        first_token_at: float | None = None
        last_token_at: float | None = None
        finish = "length"
        n_batch = int(api.lib.llama_n_batch(self._ctx)) or self.n_batch
        # Each request owns the context: drop the previous sequence's KV cache, otherwise
        # the prompt would be appended at position 0 over existing tokens (decode -1).
        api.lib.llama_memory_clear(api.lib.llama_get_memory(self._ctx), True)
        try:
            # Prompt eval must respect n_batch: feed the prompt in chunks, keeping the
            # absolute position so the KV cache stays contiguous.
            t0 = time.perf_counter()
            for start in range(0, len(tokens), n_batch):
                chunk = tokens[start : start + n_batch]
                batch, keepalive = api.make_batch(chunk, start)
                rc = api.lib.llama_decode(self._ctx, batch)
                del keepalive
                if rc != 0:
                    raise LlamaLoadError(f"llama_decode(prompt) failed with code {rc} at offset {start}")
            # llama_decode only enqueues on an async backend (Vulkan): wait for the GPU
            # before timing the prompt, otherwise prefill appears ~100x too fast.
            api.lib.llama_synchronize(self._ctx)
            prompt_ms = (time.perf_counter() - t0) * 1000.0
            pos = len(tokens)

            while generated < max_tokens:
                if cancel.is_set():
                    cancelled = True
                    finish = "cancelled"
                    break
                token = int(api.lib.llama_sampler_sample(chain, self._ctx, -1))
                api.lib.llama_sampler_accept(chain, token)
                if api.lib.llama_vocab_is_eog(self._vocab, token):
                    finish = "eog"
                    break
                piece = api.token_to_piece(self._vocab, token, special=False)
                now = time.perf_counter()
                if generated == 0:
                    ttft_ms = (now - started) * 1000.0
                    first_token_at = now
                else:
                    last_token_at = now
                pieces.append(piece)
                if on_token is not None:
                    on_token(piece)
                generated += 1

                step_batch, step_keepalive = api.make_batch([token], pos)
                rc = api.lib.llama_decode(self._ctx, step_batch)
                del step_keepalive
                if rc != 0:
                    finish = "aborted" if rc == 2 else "error"
                    break
                pos += 1
        finally:
            api.clear_abort_callback(self._ctx)
            api.lib.llama_sampler_free(chain)

        if cancel.is_set() and finish in ("aborted", "error"):
            # The abort callback can end a CPU decode mid-token; that is still a cancellation.
            cancelled = True
            finish = "cancelled"

        total_ms = (time.perf_counter() - started) * 1000.0
        if first_token_at is not None and last_token_at is not None:
            # Wall clock between the first and the last token: on an async backend the
            # per-step llama_decode timing only measures command submission.
            decode_ms = (last_token_at - first_token_at) * 1000.0
        if ttft_ms == 0.0:
            ttft_ms = total_ms
        decode_tokens = max(generated - 1, 1)
        text = "".join(pieces)
        if not thinking:
            text = self.strip_empty_thinking(text)
        return GenerationReport(
            text=text,
            prompt_tokens=len(tokens),
            generated_tokens=generated,
            ttft_ms=ttft_ms,
            prompt_ms=prompt_ms,
            decode_ms=decode_ms,
            total_ms=total_ms,
            prompt_tok_per_s=(len(tokens) / (prompt_ms / 1000.0)) if prompt_ms > 0 else 0.0,
            decode_tok_per_s=(decode_tokens / (decode_ms / 1000.0)) if decode_ms > 0 else 0.0,
            finish=finish,
            cancelled=cancelled,
            prompt_truncated_tokens=truncated,
        )
