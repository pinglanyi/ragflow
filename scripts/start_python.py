"""Start a Python service with this venv's NVIDIA libraries, not system cuDNN."""

import importlib
import os
from pathlib import Path
import runpy
import sys
import sysconfig


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
            f"Torch uses CUDA 13 but ONNX Runtime {ort.__version__} is the older CUDA build. "
            "Install the tested onnxruntime-gpu==1.27.0 in this venv; do not run uv sync back to 1.23.2."
        )
    print(f"[runtime] Python={sys.executable} Torch={torch.__version__} CUDA={cuda} "
          f"ORT={ort.__version__} providers={ort.get_available_providers()}", flush=True)


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
    load_runtime()
    if sys.argv[1] == "--check":
        print("[runtime] Import check passed. This is not an OCR/GPU inference test.", flush=True)
        return
    target = Path(sys.argv[1]).resolve()
    sys.argv = [str(target), *sys.argv[2:]]
    sys.path.insert(0, str(target.parent))
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
