"""Report task executors that share this stack's Redis queue without this stack's runtime.

Foreign executors (another checkout or an older deployment pointed at the same Redis)
consume tasks from the same queue. Their processes have no access to this venv's CUDA
libraries, so any OCR task they pick silently runs on CPU. This check is advisory: it
prints what shares the queue and never stops another deployment by itself.
"""

import argparse
import os
from pathlib import Path
import time

import yaml


def expected_executors(types, count, offset):
    """Executor names this stack registers, matching task_executor.py's CONSUMER_NAME."""
    return {f"task_executor_{task_type}_{index + offset}" for task_type in types for index in range(count)}


def heartbeat_age(scores, now):
    """Age in seconds of the newest heartbeat for an executor, or None when it never reported."""
    if not scores:
        return None
    newest = float(scores[0])
    if newest > 1e11:  # epoch milliseconds
        newest /= 1000.0
    return max(0.0, now - newest)


def classify(members, expected, ages, stale_after):
    """Split registered executors into ours, foreign-but-alive and foreign residue."""
    ours, live, stale = [], [], []
    for name in sorted(members):
        if name in expected:
            ours.append(name)
            continue
        age = ages.get(name)
        if age is not None and age <= stale_after:
            live.append(name)
        else:
            stale.append(name)
    return ours, live, stale


def redis_client(conf):
    import valkey

    redis_conf = conf.get("redis") or {}
    host, _, port = str(redis_conf.get("host", "localhost:6379")).partition(":")
    return valkey.Redis(
        host=host or "localhost",
        port=int(port or 6379),
        password=redis_conf.get("password") or None,
        db=int(redis_conf.get("db", 0) or 0),
        decode_responses=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conf", default=os.environ.get("RAGFLOW_SERVICE_CONF", "conf/service_conf.yaml"))
    parser.add_argument("--stale-after", type=float, default=float(os.environ.get("WORKER_HEARTBEAT_TIMEOUT", "120")), help="seconds without a heartbeat before an executor counts as residue")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when an external executor is alive")
    args = parser.parse_args()

    conf = yaml.safe_load(Path(args.conf).read_text(encoding="utf-8")) or {}
    expected = expected_executors(
        os.environ.get("TASK_EXECUTOR_TYPES", "common").split(),
        int(os.environ.get("TASK_EXECUTOR_COUNT", "3")),
        int(os.environ.get("TASK_EXECUTOR_OFFSET", "3")),
    )

    client = redis_client(conf)
    members = set(client.smembers("TASKEXE") or [])
    now = time.time()
    ages = {}
    for name in members:
        scores = [score for _, score in client.zrevrange(name, 0, 0, withscores=True)]
        ages[name] = heartbeat_age(scores, now)

    ours, live, stale = classify(members, expected, ages, args.stale_after)
    print(f"[executors] 本栈应注册: {', '.join(sorted(expected))}")
    print(f"[executors] Redis 已注册 {len(members)} 个, 其中属于本栈 {len(ours)} 个")
    for name in live:
        print(f"[executors] WARNING 外部执行器活跃: {name} (心跳 {ages[name]:.0f}s 前) —— 它抢同一队列的任务, 且没有本仓库的 GPU 运行库, OCR 会走 CPU")
    if stale:
        print(f"[executors] 已失效残留(可忽略): {', '.join(stale)}")
    if live:
        print("[executors] 处理: 停掉那个实例 (pgrep -af task_executor.py), 或让本栈改用独立 Redis DB")
        return 1 if args.strict else 0
    print("[executors] 未发现外部执行器竞争队列 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
