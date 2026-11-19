"""稳定性自检（soak test）——不依赖真实 MySQL。

用途：在缺少 DB 凭据时，先验证「代码层」长时间反复执行不崩、无内存持续增长。
真实连库的 72 小时 soak 需提供 DB_USER/DB_PASSWORD/SECRET_KEY，见总纲 §10.2。

运行：
    python register/tests/soak.py --minutes 5     # 快速自检
    python register/tests/soak.py --hours 72      # 长跑（前台阻塞）

退出码：0 通过，1 失败。
"""

import argparse
import gc
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "register", "tests")


def rss_mb():
    """当前进程 RSS（MB）。优先 psutil（跨平台可靠），否则读 /proc。"""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except ImportError:
        pass
    except Exception:
        return -1
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return -1


def run_round(n):
    """跑一轮完整测试，返回 (ok, 耗时秒, 输出末行)。"""
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    ok = p.returncode == 0
    tail = (p.stdout or p.stderr).strip().splitlines()[-1] if (p.stdout or p.stderr).strip() else ""
    return ok, time.time() - t0, tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--hours", type=float, default=0)
    args = ap.parse_args()
    duration = args.hours * 3600 if args.hours else args.minutes * 60

    print(f"[soak] 目标时长 {duration / 60:.1f} 分钟，起始 RSS {rss_mb():.1f} MB", flush=True)
    start = time.time()
    rss_samples = []
    rounds = 0
    failures = 0

    while time.time() - start < duration:
        ok, elapsed, tail = run_round(rounds + 1)
        rounds += 1
        gc.collect()
        rss = rss_mb()
        rss_samples.append(rss)
        if not ok:
            failures += 1
        print(f"[soak] 第 {rounds:3d} 轮 {'OK ' if ok else 'FAIL'} "
              f"{elapsed:5.2f}s  RSS {rss:7.1f}MB  {tail[:60]}", flush=True)
        if not ok:
            print(f"[soak] 失败输出:\n{tail}", flush=True)
            return 1

        sleep_for = min(300, max(0, duration - (time.time() - start)))
        if sleep_for > 0:
            time.sleep(sleep_for)

    # 内存趋势：后 1/3 均值 vs 前 1/3 均值，涨幅 > 30% 视为泄漏嫌疑
    if len(rss_samples) >= 3:
        k = max(1, len(rss_samples) // 3)
        early = sum(rss_samples[:k]) / k
        late = sum(rss_samples[-k:]) / k
        growth = (late - early) / early * 100 if early > 0 else 0
        print(f"[soak] 内存趋势 前段 {early:.1f}MB → 后段 {late:.1f}MB "
              f"({growth:+.1f}%)", flush=True)
        if growth > 30:
            print("[soak] WARN: 内存涨幅 >30%，疑似泄漏，需人工复核", flush=True)
            return 1

    print(f"[soak] 完成：{rounds} 轮，失败 {failures}，耗时 "
          f"{(time.time() - start) / 60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
