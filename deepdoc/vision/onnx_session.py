"""Serialize shared vision sessions and recover from GPU allocator failures."""

import logging
import threading

import numpy as np


class ResilientSession:
    def __init__(self, session, cpu_factory, model_path):
        self._session = session
        self._cpu_factory = cpu_factory
        self._model_path = model_path
        self._lock = threading.RLock()
        self._using_cpu = False
        self._cpu_run_options = None

    def __getattr__(self, name):
        return getattr(self._session, name)

    def run(self, output_names, input_feed, run_options=None):
        inputs = {}
        for name, value in input_feed.items():
            if not isinstance(value, np.ndarray) or any(size <= 0 for size in value.shape):
                raise ValueError(f"Invalid ONNX input {name}: expected non-empty numpy tensor")
            if not np.isfinite(value).all():
                raise ValueError(f"Invalid ONNX input {name}: non-finite values")
            inputs[name] = np.ascontiguousarray(value)
        # Sessions are cached across OCR calls. Do not concurrently run/shrink the
        # same CUDA arena while another request is using its convolution workspace.
        with self._lock:
            try:
                return self._session.run(output_names, inputs, self._cpu_run_options if self._using_cpu else run_options)
            except Exception as exc:
                message = str(exc).lower()
                gpu_failure = any(marker in message for marker in (
                    "bfcarena", "allocaterawinternal", "cuda out of memory",
                    "cuda_error_out_of_memory", "cuda failure 2: out of memory",
                    "cudnn_status_alloc_failed", "cublas_status_alloc_failed",
                ))
                if self._cpu_factory is None or self._using_cpu or not gpu_failure:
                    raise
                shapes = {name: {"shape": list(value.shape), "dtype": str(value.dtype), "bytes": value.nbytes} for name, value in inputs.items()}
                logging.warning("DeepDOC GPU inference failed for %s; retrying this model on CPU. inputs=%s error=%s", self._model_path, shapes, exc)
                session, options = self._cpu_factory()
                self._session = session
                self._cpu_run_options = options
                self._using_cpu = True
                # CPU errors must propagate; never pretend OCR succeeded.
                return self._session.run(output_names, inputs, options)
