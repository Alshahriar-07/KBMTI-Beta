"""ctypes bindings for the pinned llama.cpp runtime (release ``b12503``).

This is the only module in KIE that is allowed to touch ``ctypes``. Everything above it
(:mod:`app.kie.runtime.llama`) works with plain Python objects.

The struct layouts and signatures below were transcribed from ``include/llama.h`` at tag
``b12503``. llama.cpp's C ABI is not stable across releases, so:

* the release tag is pinned in ``backend/models/kie/manifest.json``,
* every field order/type here must be re-checked against that tag before upgrading,
* :meth:`LlamaApi.describe_abi` returns sizes and the library's own default values so a
  layout mismatch shows up immediately (garbage defaults) instead of as a silent crash.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_bool,
    c_char_p,
    c_float,
    c_int8,
    c_int32,
    c_size_t,
    c_uint32,
    c_void_p,
)
from dataclasses import dataclass, field
from pathlib import Path

RUNTIME_TAG = "b12503"

# llama_token, llama_pos and llama_seq_id are all int32_t in this tag.
LlamaToken = c_int32


class LlamaLoadError(RuntimeError):
    """Raised when the runtime DLLs or the model cannot be brought up."""


class LlamaBatch(Structure):
    _fields_ = [
        ("n_tokens", c_int32),
        ("token", POINTER(c_int32)),
        ("embd", POINTER(c_float)),
        ("pos", POINTER(c_int32)),
        ("n_seq_id", POINTER(c_int32)),
        ("seq_id", POINTER(POINTER(c_int32))),
        ("logits", POINTER(c_int8)),
    ]


class LlamaModelParams(Structure):
    _fields_ = [
        ("devices", c_void_p),
        ("tensor_buft_overrides", c_void_p),
        ("n_gpu_layers", c_int32),
        ("split_mode", c_int32),
        ("load_mode", c_int32),
        ("lazy_mode", c_int32),
        ("main_gpu", c_int32),
        ("tensor_split", POINTER(c_float)),
        ("progress_callback", c_void_p),
        ("progress_callback_user_data", c_void_p),
        ("kv_overrides", c_void_p),
        ("vocab_only", c_bool),
        ("check_tensors", c_bool),
        ("use_extra_bufts", c_bool),
        ("no_host", c_bool),
        ("no_alloc", c_bool),
        ("load_mtp", c_bool),
    ]


class LlamaContextParams(Structure):
    _fields_ = [
        ("n_ctx", c_uint32),
        ("n_batch", c_uint32),
        ("n_ubatch", c_uint32),
        ("n_seq_max", c_uint32),
        ("n_rs_seq", c_uint32),
        ("n_outputs_max", c_uint32),
        ("n_outputs_max_per_seq", c_uint32),
        ("n_threads", c_int32),
        ("n_threads_batch", c_int32),
        ("ctx_type", c_int32),
        ("rope_scaling_type", c_int32),
        ("pooling_type", c_int32),
        ("attention_type", c_int32),
        ("flash_attn_type", c_int32),
        ("rope_freq_base", c_float),
        ("rope_freq_scale", c_float),
        ("yarn_ext_factor", c_float),
        ("yarn_attn_factor", c_float),
        ("yarn_beta_fast", c_float),
        ("yarn_beta_slow", c_float),
        ("yarn_orig_ctx", c_uint32),
        ("cb_eval", c_void_p),
        ("cb_eval_user_data", c_void_p),
        ("type_k", c_int32),
        ("type_v", c_int32),
        ("moe_cache_size", c_size_t),
        ("moe_cache_cpu_share", c_float),
        ("abort_callback", c_void_p),
        ("abort_callback_data", c_void_p),
        ("embeddings", c_bool),
        ("offload_kqv", c_bool),
        ("no_perf", c_bool),
        ("op_offload", c_bool),
        ("swa_full", c_bool),
        ("kv_unified", c_bool),
        ("samplers", c_void_p),
        ("n_samplers", c_size_t),
        ("ctx_other", c_void_p),
    ]


class LlamaSamplerChainParams(Structure):
    _fields_ = [("no_perf", c_bool)]


class LlamaChatMessage(Structure):
    _fields_ = [("role", c_char_p), ("content", c_char_p)]


GGML_LOG_CALLBACK = CFUNCTYPE(None, c_int32, c_char_p, c_void_p)
GGML_ABORT_CALLBACK = CFUNCTYPE(c_bool, c_void_p)

# ggml log levels
LOG_LEVEL_NONE = 0
LOG_LEVEL_DEBUG = 1
LOG_LEVEL_INFO = 2
LOG_LEVEL_WARN = 3
LOG_LEVEL_ERROR = 4
LOG_LEVEL_CONT = 5


@dataclass
class LogCapture:
    """Collects llama.cpp/ggml log output.

    ggml writes partial lines (it flushes on newlines, but continuation records arrive as
    ``LOG_LEVEL_CONT``), so text is buffered and split into lines on demand.
    """

    lines: list[tuple[int, str]] = field(default_factory=list)
    _buffer: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, level: int, text: bytes | None, _user_data: int | None) -> None:
        if not text:
            return
        chunk = text.decode("utf-8", "replace")
        with self._lock:
            self._buffer += chunk
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    self.lines.append((level, line))

    def snapshot(self) -> list[tuple[int, str]]:
        with self._lock:
            out = list(self.lines)
            if self._buffer.strip():
                out.append((LOG_LEVEL_CONT, self._buffer))
        return out

    def text(self) -> str:
        return "\n".join(line for _level, line in self.snapshot())

    def clear(self) -> None:
        with self._lock:
            self.lines.clear()
            self._buffer = ""


class LlamaApi:
    """Loaded ``llama.dll`` plus the function signatures KIE uses."""

    def __init__(self, dll_dir: Path, log: LogCapture | None = None) -> None:
        # add_dll_directory() rejects relative paths, and llama.dll resolves its own
        # dependencies (ggml*.dll) from this directory at load time.
        self.dll_dir = Path(dll_dir).resolve()
        self.log = log or LogCapture()
        if not (self.dll_dir / "llama.dll").is_file():
            raise LlamaLoadError(
                f"llama.dll not found in {self.dll_dir}. Run scripts/kie_fetch_runtime.py to install the pinned runtime."
            )
        self._dll_handles: list[object] = []
        self._log_cb = GGML_LOG_CALLBACK(self.log)
        self._abort_cb: GGML_ABORT_CALLBACK | None = None
        self._load()

    # -- loading ---------------------------------------------------------
    def _load(self) -> None:
        if os.name == "nt":
            try:
                os.add_dll_directory(str(self.dll_dir))
            except (AttributeError, OSError) as exc:  # pragma: no cover - platform specific
                raise LlamaLoadError(f"could not register DLL directory {self.dll_dir}: {exc}") from exc
        try:
            # ggml is imported by llama.dll at load time; load it first so a missing
            # dependency surfaces with the DLL name rather than a bare WinError.
            self.ggml = ctypes.CDLL(str(self.dll_dir / "ggml.dll"))
            self._dll_handles.append(self.ggml)
            self.lib = ctypes.CDLL(str(self.dll_dir / "llama.dll"))
        except OSError as exc:
            raise LlamaLoadError(f"could not load llama.cpp runtime from {self.dll_dir}: {exc}") from exc
        self._bind()
        self._bind_ggml()

    def _bind(self) -> None:
        lib = self.lib
        p = c_void_p

        def sig(name: str, restype, argtypes) -> None:
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = argtypes

        sig("llama_log_set", None, [GGML_LOG_CALLBACK, p])
        sig("llama_backend_init", None, [])
        sig("llama_backend_free", None, [])
        sig("llama_version", c_char_p, [])
        sig("llama_print_system_info", c_char_p, [])
        sig("llama_supports_gpu_offload", c_bool, [])
        sig("llama_supports_mmap", c_bool, [])
        sig("llama_supports_mlock", c_bool, [])
        sig("llama_max_devices", c_size_t, [])

        sig("llama_model_default_params", LlamaModelParams, [])
        sig("llama_context_default_params", LlamaContextParams, [])
        sig("llama_sampler_chain_default_params", LlamaSamplerChainParams, [])

        sig("llama_model_load_from_file", p, [c_char_p, LlamaModelParams])
        sig("llama_model_free", None, [p])
        sig("llama_init_from_model", p, [p, LlamaContextParams])
        sig("llama_free", None, [p])

        sig("llama_model_get_vocab", p, [p])
        sig("llama_model_n_layer", c_int32, [p])
        sig("llama_model_n_ctx_train", c_int32, [p])
        sig("llama_model_n_embd", c_int32, [p])
        sig("llama_model_n_head", c_int32, [p])
        sig("llama_model_n_head_kv", c_int32, [p])
        sig("llama_model_n_params", ctypes.c_uint64, [p])
        sig("llama_model_size", ctypes.c_uint64, [p])
        sig("llama_model_desc", c_int32, [p, c_char_p, c_size_t])
        sig("llama_model_chat_template", c_char_p, [p, c_char_p])
        sig("llama_model_meta_val_str", c_int32, [p, c_char_p, c_char_p, c_size_t])

        sig("llama_synchronize", None, [p])
        sig("llama_get_memory", p, [p])
        sig("llama_memory_clear", None, [p, c_bool])
        sig("llama_n_ctx", c_uint32, [p])
        sig("llama_n_batch", c_uint32, [p])
        sig("llama_n_ubatch", c_uint32, [p])
        sig("llama_set_n_threads", None, [p, c_int32, c_int32])
        sig("llama_set_abort_callback", None, [p, GGML_ABORT_CALLBACK, p])

        sig("llama_vocab_n_tokens", c_int32, [p])
        sig("llama_vocab_is_eog", c_bool, [p, LlamaToken])
        sig("llama_vocab_bos", LlamaToken, [p])
        sig("llama_vocab_eos", LlamaToken, [p])
        sig("llama_tokenize", c_int32, [p, c_char_p, c_int32, POINTER(LlamaToken), c_int32, c_bool, c_bool])
        sig("llama_token_to_piece", c_int32, [p, LlamaToken, c_char_p, c_int32, c_int32, c_bool])
        sig("llama_chat_apply_template", c_int32, [c_char_p, POINTER(LlamaChatMessage), c_size_t, c_bool, c_char_p, c_int32])

        sig("llama_batch_get_one", LlamaBatch, [POINTER(LlamaToken), c_int32])
        sig("llama_decode", c_int32, [p, LlamaBatch])

        sig("llama_sampler_chain_init", p, [LlamaSamplerChainParams])
        sig("llama_sampler_chain_add", None, [p, p])
        sig("llama_sampler_init_top_k", p, [c_int32])
        sig("llama_sampler_init_top_p", p, [c_float, c_size_t])
        sig("llama_sampler_init_temp", p, [c_float])
        sig("llama_sampler_init_penalties", p, [c_int32, c_int32, c_float, c_float, c_float])
        sig("llama_sampler_init_dist", p, [c_uint32])
        sig("llama_sampler_init_greedy", p, [])
        sig("llama_sampler_sample", LlamaToken, [p, p, c_int32])
        sig("llama_sampler_accept", None, [p, LlamaToken])
        sig("llama_sampler_reset", None, [p])
        sig("llama_sampler_free", None, [p])

        self.lib.llama_log_set(self._log_cb, None)

    def _bind_ggml(self) -> None:
        ggml = self.ggml
        # Only a small subset of ggml is exported from ggml.dll; this build does not
        # auto-load backend plugins from llama_backend_init(), so KIE loads them explicitly
        # from the pinned runtime directory (never from PATH or CWD).
        ggml.ggml_backend_load_all_from_path.argtypes = [c_char_p]
        ggml.ggml_backend_load_all_from_path.restype = c_int32
        ggml.ggml_backend_dev_count.argtypes = []
        ggml.ggml_backend_dev_count.restype = c_size_t
        ggml.ggml_backend_dev_by_type.argtypes = [c_int32]
        ggml.ggml_backend_dev_by_type.restype = c_void_p
        # Device names are available from this tag's backend API, so diagnostics do not
        # rely on the one-time Vulkan discovery log line being emitted again on reload.
        for name in ("ggml_backend_dev_name", "ggml_backend_dev_description"):
            fn = getattr(ggml, name, None)
            if fn is not None:
                fn.argtypes = [c_void_p]
                fn.restype = c_char_p
        self._backends_loaded = False

    def load_backends(self, search_path: Path | None = None) -> dict[str, object]:
        """Load ggml backend plugins (Vulkan/CPU/RPC) from ``search_path``."""
        path = str((search_path or self.dll_dir).resolve())
        status = self.ggml.ggml_backend_load_all_from_path(path.encode())
        self._backends_loaded = status == 0
        gpu_device = self.ggml.ggml_backend_dev_by_type(1)
        gpu_name = self._device_text("ggml_backend_dev_name", gpu_device)
        gpu_description = self._device_text("ggml_backend_dev_description", gpu_device)
        return {
            "status": status,
            "search_path": path,
            "device_count": int(self.ggml.ggml_backend_dev_count()),
            # ``llama_supports_gpu_offload()`` is not trustworthy here: the RPC backend
            # registers itself as a GPU device, so a CPU-only plugin set reports True.
            "gpu_offload": bool(gpu_device),
            "gpu_device_present": bool(gpu_device),
            "gpu_name": gpu_name,
            "gpu_description": gpu_description,
            "llama_supports_gpu_offload": bool(self.lib.llama_supports_gpu_offload()),
        }

    def _device_text(self, function: str, device: int | None) -> str | None:
        if not device:
            return None
        fn = getattr(self.ggml, function, None)
        if fn is None:
            return None
        raw = fn(device)
        return raw.decode("utf-8", "replace") if raw else None

    @property
    def backends_loaded(self) -> bool:
        return self._backends_loaded

    # -- helpers ---------------------------------------------------------
    def describe_abi(self) -> dict[str, object]:
        """Sizes and library-provided defaults, used to detect a struct-layout mismatch."""
        mp = self.lib.llama_model_default_params()
        cp = self.lib.llama_context_default_params()
        return {
            "runtime_tag": RUNTIME_TAG,
            "llama_version": self.version(),
            "struct_sizes": {
                "llama_model_params": ctypes.sizeof(LlamaModelParams),
                "llama_context_params": ctypes.sizeof(LlamaContextParams),
                "llama_batch": ctypes.sizeof(LlamaBatch),
                "llama_sampler_chain_params": ctypes.sizeof(LlamaSamplerChainParams),
            },
            "model_defaults": {
                "n_gpu_layers": mp.n_gpu_layers,
                "split_mode": mp.split_mode,
                "load_mode": mp.load_mode,
                "lazy_mode": mp.lazy_mode,
                "main_gpu": mp.main_gpu,
                "use_extra_bufts": bool(mp.use_extra_bufts),
                "check_tensors": bool(mp.check_tensors),
            },
            "context_defaults": {
                "n_ctx": cp.n_ctx,
                "n_batch": cp.n_batch,
                "n_ubatch": cp.n_ubatch,
                "n_seq_max": cp.n_seq_max,
                "n_threads": cp.n_threads,
                "n_threads_batch": cp.n_threads_batch,
                "flash_attn_type": cp.flash_attn_type,
                "type_k": cp.type_k,
                "type_v": cp.type_v,
                "offload_kqv": bool(cp.offload_kqv),
                "op_offload": bool(cp.op_offload),
            },
        }

    def version(self) -> str:
        raw = self.lib.llama_version()
        return raw.decode("utf-8", "replace") if raw else "unknown"

    def system_info(self) -> str:
        raw = self.lib.llama_print_system_info()
        return raw.decode("utf-8", "replace") if raw else ""

    def backend_init(self) -> None:
        self.lib.llama_backend_init()

    def backend_free(self) -> None:
        self.lib.llama_backend_free()

    def model_default_params(self) -> LlamaModelParams:
        return self.lib.llama_model_default_params()

    def context_default_params(self) -> LlamaContextParams:
        return self.lib.llama_context_default_params()

    def sampler_chain_default_params(self) -> LlamaSamplerChainParams:
        return self.lib.llama_sampler_chain_default_params()

    def set_abort_callback(self, ctx: int, fn) -> None:
        """Install a decode abort callback (``bool (*)(void*)``; honoured on CPU execution)."""
        self._abort_cb = GGML_ABORT_CALLBACK(fn)
        self.lib.llama_set_abort_callback(ctx, self._abort_cb, None)

    def clear_abort_callback(self, ctx: int) -> None:
        self.lib.llama_set_abort_callback(ctx, GGML_ABORT_CALLBACK(0), None)
        self._abort_cb = None

    def tokenize(self, vocab: int, text: str, add_special: bool = True, parse_special: bool = True) -> list[int]:
        data = text.encode("utf-8")
        probe = (LlamaToken * 1)()
        needed = self.lib.llama_tokenize(vocab, data, len(data), probe, 0, add_special, parse_special)
        if needed == 0:
            return []
        if needed < 0:
            needed = -needed
        buf = (LlamaToken * needed)()
        written = self.lib.llama_tokenize(vocab, data, len(data), buf, needed, add_special, parse_special)
        if written < 0:
            raise LlamaLoadError(f"tokenize failed (needed {-written} tokens)")
        return list(buf[:written])

    def token_to_piece(self, vocab: int, token: int, special: bool = True) -> str:
        buf = ctypes.create_string_buffer(256)
        written = self.lib.llama_token_to_piece(vocab, token, buf, len(buf), 0, special)
        if written < 0:
            buf = ctypes.create_string_buffer(-written)
            written = self.lib.llama_token_to_piece(vocab, token, buf, len(buf), 0, special)
        if written < 0:
            return ""
        return bytes(buf.raw[:written]).decode("utf-8", "replace")

    def apply_chat_template(
        self,
        template: str,
        messages: list[tuple[str, str]],
        add_assistant: bool = True,
    ) -> str:
        arr = (LlamaChatMessage * len(messages))()
        encoded: list[bytes] = []
        for i, (role, content) in enumerate(messages):
            role_b = role.encode("utf-8")
            content_b = content.encode("utf-8")
            encoded.extend([role_b, content_b])
            arr[i].role = role_b
            arr[i].content = content_b
        tmpl = template.encode("utf-8")
        needed = self.lib.llama_chat_apply_template(tmpl, arr, len(messages), add_assistant, None, 0)
        if needed < 0:
            raise LlamaLoadError("chat template rejected the message list")
        buf = ctypes.create_string_buffer(needed + 1)
        written = self.lib.llama_chat_apply_template(
            tmpl, arr, len(messages), add_assistant, ctypes.cast(buf, c_char_p), needed + 1
        )
        if written < 0:
            raise LlamaLoadError("chat template rendering failed")
        return bytes(buf.raw[:written]).decode("utf-8", "replace")

    def model_meta(self, model: int, key: str) -> str | None:
        buf = ctypes.create_string_buffer(4096)
        n = self.lib.llama_model_meta_val_str(model, key.encode(), buf, len(buf))
        if n < 0:
            return None
        return buf.value.decode("utf-8", "replace")

    def model_desc(self, model: int) -> str:
        buf = ctypes.create_string_buffer(512)
        n = self.lib.llama_model_desc(model, buf, len(buf))
        if n < 0:
            return "unknown"
        return buf.value.decode("utf-8", "replace")

    def make_batch(self, tokens: list[int], pos_start: int, logits_last_only: bool = True) -> tuple[LlamaBatch, list]:
        """Build a single-sequence batch.

        Returns ``(batch, keepalive)``. The caller must keep ``keepalive`` referenced until
        ``llama_decode`` returns, otherwise the pointed-to buffers are garbage-collected.
        """
        n = len(tokens)
        token_arr = (c_int32 * n)(*tokens)
        pos_arr = (c_int32 * n)(*[pos_start + i for i in range(n)])
        n_seq = (c_int32 * n)(*[1] * n)
        seq0 = (c_int32 * 1)(0)
        single = ctypes.cast(seq0, POINTER(c_int32))
        seq_ids = (POINTER(c_int32) * n)(*([single] * n))
        logits = (c_int8 * n)()
        if n:
            if logits_last_only:
                logits[n - 1] = 1
            else:
                for i in range(n):
                    logits[i] = 1
        batch = LlamaBatch(n, token_arr, None, pos_arr, n_seq, seq_ids, logits)
        keepalive = [token_arr, pos_arr, n_seq, seq0, seq_ids, logits]
        return batch, keepalive
