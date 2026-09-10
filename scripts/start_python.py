"""Start a Python service with this venv's NVIDIA libraries, not system cuDNN."""

import ctypes
import importlib
import os
from pathlib import Path
import runpy
import sys
import sysconfig

ALLOW_CPU_ENV = "RAGFLOW_ALLOW_CPU"
REQUIRE_GPU_ENV = "RAGFLOW_REQUIRE_GPU"
# Services that run OCR/ingestion must not start on a silent CPU fallback.
GPU_TARGETS = ("task_executor.py",)


def library_path(site_paths, inherited):
    directories = []
    for site_path in site_paths:
        base = Path(site_path)
        # cuDNN dynamically opens sibling engine libraries by soname. They must
        # precede /usr/local/cuda-* even when Torch has preloaded the main library.
        candidates = [base / "nvidia/cudnn/lib", base / "torch/lib"]
        candidates.extend(sorted((base / "nvidia").glob("*/lib")))
        directories.extend(str(p) for p in candidates if p.is_dir())
    directories.extend(p for p in inherited.split(os.pathsep) if p)
    return os.pathsep.join(dict.fromkeys(directories))


def load_runtime():
    # Must happen in the service process, before any transitive ORT import.
    torch = importlib.import_module("torch")
    ort = importlib.import_module("onnxruntime")
    cuda = torch.version.cuda or "CPU"
    ort_version = tuple(int(part) for part in ort.__version__.split(".")[:2])
    if cuda.startswith("13.") and ort_version < (1, 27):
        raise RuntimeError(
            f"Torch uses CUDA 13 but ONNX Runtime {ort.__version__} is the older CUDA build. Install the tested onnxruntime-gpu==1.27.0 in this venv; do not run uv sync back to 1.23.2."
        )
    print(f"[runtime] Python={sys.executable} Torch={torch.__version__} CUDA={cuda} ORT={ort.__version__} providers={ort.get_available_providers()}", flush=True)
    return torch, ort


def enabled(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def gpu_strict(target):
    """OCR paths fail loudly; other services only warn unless a GPU is demanded."""
    if enabled(ALLOW_CPU_ENV):
        return False
    if enabled(REQUIRE_GPU_ENV):
        return True
    return target == "--check" or target.endswith(GPU_TARGETS)


def cuda_provider_library(ort):
    """Path of the CUDA execution provider shipped with this onnxruntime, if any."""
    capi = Path(ort.__file__).resolve().parent / "capi"
    for name in ("libonnxruntime_providers_cuda.so", "onnxruntime_providers_cuda.so", "onnxruntime_providers_cuda.dll"):
        candidate = capi / name
        if candidate.is_file():
            return candidate
    return None


def provider_library_error(path):
    """Empty string when the provider library and its dependencies can be loaded."""
    try:
        ctypes.CDLL(str(path), mode=getattr(os, "RTLD_NOW", 2))
    except OSError as exc:
        return str(exc)
    return ""


def verify_gpu(torch, ort, strict):
    """Refuse a silent CPU fallback: torch must see a GPU and ORT must load its CUDA provider."""
    problems = []
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None and not visible.strip():
        problems.append("CUDA_VISIBLE_DEVICES is set but empty, which hides every GPU")

    available = False
    device_count = 0
    try:
        available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count())
    except Exception as exc:  # missing driver, broken libraries, ...
        problems.append(f"torch.cuda probe failed: {exc}")
    if not available or device_count < 1:
        problems.append(f"torch sees no usable GPU (is_available={available}, device_count={device_count})")

    providers = list(ort.get_available_providers())
    if "CUDAExecutionProvider" not in providers:
        problems.append(f"onnxruntime providers={providers} contain no CUDAExecutionProvider")
    else:
        library = cuda_provider_library(ort)
        if library is None:
            problems.append("onnxruntime ships no CUDA provider library")
        elif error := provider_library_error(library):
            problems.append(f"cannot load {library.name}: {error}")

    summary = f"torch={torch.__version__} cuda={torch.version.cuda} ort={ort.__version__} providers={providers} devices={device_count}"
    if problems:
        message = "; ".join(problems)
        if strict:
            raise RuntimeError(f"GPU runtime unusable: {message}. Check nvidia-smi and unset an empty CUDA_VISIBLE_DEVICES, or export {ALLOW_CPU_ENV}=1 to accept CPU-only OCR.")
        print(f"[runtime] WARNING GPU runtime unusable: {message}", flush=True)
    print(f"[runtime] GPU {summary}", flush=True)
    return {"available": available, "device_count": device_count, "providers": providers}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: start_python.py --check | service.py [arguments...]")
    if sys.platform.startswith("linux"):
        sites = dict.fromkeys([sysconfig.get_path("purelib"), sysconfig.get_path("platlib")])
        current = os.environ.get("LD_LIBRARY_PATH", "")
        desired = library_path(sites, current)
        if desired != current:
            # The dynamic loader needs this environment BEFORE Python starts.
            # exec preserves the PID tracked by start.sh; the computation is idempotent.
            env = {**os.environ, "LD_LIBRARY_PATH": desired}
            os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env)
    print(f"[runtime] LD_LIBRARY_PATH={os.environ.get('LD_LIBRARY_PATH', '')}", flush=True)
    torch, ort = load_runtime()
    try:
        status = verify_gpu(torch, ort, gpu_strict(sys.argv[1]))
    except RuntimeError as exc:
        raise SystemExit(f"[runtime] {exc}")
    if sys.argv[1] == "--check":
        if status["available"]:
            print("[runtime] Check passed: CUDA is visible and the ORT CUDA provider loads. This is not an OCR accuracy test.", flush=True)
        else:
            print(f"[runtime] Check finished with CPU-only OCR (allowed by {ALLOW_CPU_ENV}); the GPU checks above did not pass.", flush=True)
        return
    target = Path(sys.argv[1]).resolve()
    sys.argv = [str(target), *sys.argv[2:]]
    sys.path.insert(0, str(target.parent))
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
