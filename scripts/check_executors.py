"""Report executor queue isolation using heartbeat evidence, without stopping processes.

Sharing Redis or an executor index does not establish queue membership or GPU use.
Missing queue reports are explicitly marked unknown.
"""

import argparse
import json
import os
import time
from pathlib import Path

import yaml

from common.task_queue import task_queue_names


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


def split_queue_peers(names, expected_queues, reported_queues):
    """Unknown old workers must not be falsely called competitors or isolated."""
    shared, isolated, unknown = [], [], []
    for name in names:
        queues = reported_queues.get(name)
        if not isinstance(queues, list) or not queues or not all(isinstance(queue, str) for queue in queues):
            unknown.append(name)
        elif set(queues) & set(expected_queues):
            shared.append(name)
        else:
            isolated.append(name)
    return shared, isolated, unknown


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
    parser.add_argument("--strict", action="store_true", help="exit non-zero for competing, unknown or mismatched executor queues")
    args = parser.parse_args()

    conf = yaml.safe_load(Path(args.conf).read_text(encoding="utf-8")) or {}
    expected = expected_executors(
        os.environ.get("TASK_EXECUTOR_TYPES", "common").split(),
        int(os.environ.get("TASK_EXECUTOR_COUNT", "3")),
        int(os.environ.get("TASK_EXECUTOR_OFFSET", "6")),
    )

    client = redis_client(conf)
    members = set(client.smembers("TASKEXE") or [])
    now = time.time()
    ages = {}
    reported_queues = {}
    for name in members:
        entries = client.zrevrange(name, 0, 0, withscores=True)
        scores = [score for _, score in entries]
        ages[name] = heartbeat_age(scores, now)
        if entries:
            try:
                reported_queues[name] = json.loads(entries[0][0]).get("task_queues")
            except (TypeError, ValueError, AttributeError):
                pass

    ours, live, stale = classify(members, expected, ages, args.stale_after)
    queues = task_queue_names()
    mismatched = [name for name in ours if reported_queues.get(name) != queues or ages.get(name) is None or ages[name] > args.stale_after]
    live, isolated, unknown = split_queue_peers(live, queues, reported_queues)
    print(f"[executors] 本栈应注册: {', '.join(sorted(expected))}")
    print(f"[executors] 本栈队列: {', '.join(queues)}")
    print(f"[executors] Redis 已注册 {len(members)} 个, 其中属于本栈 {len(ours)} 个")
    for name in mismatched:
        print(f"[executors] WARNING 本栈执行器队列未确认或不匹配: {name} —— 核对最新心跳并重启本栈后端与 worker")
    for name in live:
        print(f"[executors] WARNING 外部执行器活跃: {name} (心跳 {ages[name]:.0f}s 前) —— 它会消费同一队列; 代码版本及 GPU/OCR 运行环境尚未核实")
    for name in isolated:
        print(f"[executors] 队列已隔离: {name} —— 未监听本栈队列")
    for name in unknown:
        print(f"[executors] 队列未知: {name} —— 旧心跳未报告监听队列，不能仅凭编号判断是否竞争")
    if stale:
        print(f"[executors] 已失效残留(可忽略): {', '.join(stale)}")
    if live or mismatched:
        print("[executors] 处理: 核对本栈后端与 worker 的 RAGFLOW_TASK_QUEUE_NAMESPACE，并重启本栈；不要停止其他用户的执行器")
    if live or unknown or mismatched:
        return 1 if args.strict else 0
    print("[executors] 未发现外部执行器竞争队列 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
