"""What the machine is doing, and what has been read since it was switched on.

One honest note about the numbers below. On the Mac the containers run inside
a small Linux virtual machine, so what is measured here is that machine, not
macOS. That is the right thing to look at anyway: it is the memory and the
processor the pipeline actually gets, and it is where the eight gigabyte
ceiling bites. It is reported as such rather than being labelled as the Mac.
"""
import json
import logging
import os
import platform
import shutil
import time

import config
import db

log = logging.getLogger("khoj.metrics")

KEY = "khoj:machine"
STARTED = time.time()

try:
    import psutil
except ImportError:  # the container installs it, a bare checkout may not
    psutil = None


def _disk(path):
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round((usage.total - usage.free) / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "used_pct": round((usage.total - usage.free) / usage.total * 100, 1),
        }
    except Exception:
        return None


def archive_size():
    """How much of the record is on disk, and how many documents."""
    files = 0
    size = 0
    try:
        for root, _dirs, names in os.walk(config.ARCHIVE_DIR):
            for name in names:
                files += 1
                try:
                    size += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
            if files > 250000:
                break
    except Exception:
        pass
    return {"documents": files, "size_mb": round(size / 1e6, 1)}


def machine():
    """A reading of the host the containers run on."""
    out = {
        "at": time.time(),
        "kind": "the Linux machine the containers run in",
        "system": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "uptime_seconds": int(time.time() - STARTED),
        "disks": [d for d in (_disk("/"), _disk(config.ARCHIVE_DIR)) if d],
    }
    if not psutil:
        out["note"] = "psutil is not installed, so only disk figures are available"
        return out

    try:
        out["cpu"] = {
            "cores": psutil.cpu_count(logical=True),
            "busy_pct": psutil.cpu_percent(interval=0.4),
            "load_1m": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None,
        }
    except Exception:
        pass
    try:
        mem = psutil.virtual_memory()
        out["memory"] = {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb": round((mem.total - mem.available) / 1e9, 2),
            "used_pct": mem.percent,
        }
    except Exception:
        pass
    try:
        swap = psutil.swap_memory()
        out["swap"] = {"total_gb": round(swap.total / 1e9, 2),
                       "used_pct": swap.percent}
    except Exception:
        pass
    try:
        boot = psutil.boot_time()
        out["host_uptime_seconds"] = int(time.time() - boot)
    except Exception:
        pass
    try:
        # What this process itself is costing, which is the part we control.
        proc = psutil.Process()
        with proc.oneshot():
            out["agents"] = {
                "memory_mb": round(proc.memory_info().rss / 1e6, 1),
                "threads": proc.num_threads(),
                "cpu_pct": proc.cpu_percent(interval=None),
            }
    except Exception:
        pass
    return out


def snapshot():
    """Everything the stats page shows, in one object."""
    import crawl
    import merge
    import watch

    reading = db.totals()
    return {
        "at": time.time(),
        "machine": machine(),
        "archive": archive_size(),
        "totals": reading,
        "by_outlet_seen": db.outlet_totals("seen")[:25],
        "by_outlet_claims": db.outlet_totals("claims")[:25],
        "sources": crawl.source_health(),
        "watching": len(watch.listing()),
        "merges_waiting": len(merge.reviews()),
        "summary": summarise(reading),
    }


def summarise(reading):
    """The running totals in a sentence, with the ratio that actually matters."""
    seen = reading.get("seen", 0)
    processed = reading.get("processed", 0)
    claims = reading.get("claims", 0)
    if not seen:
        return "Nothing has been read yet."
    since = (reading.get("since") or "")[:10]
    yield_rate = round(claims / processed, 2) if processed else 0
    return (
        f"{seen:,} article listings have been looked at since {since}. "
        f"{processed:,} were worth reading in full and produced {claims:,} links, "
        f"which is {yield_rate} links for every article the model read. "
        f"{reading.get('duplicate', 0):,} were thrown away as near copies of "
        "something already seen."
    )


def publish():
    try:
        db.rds().set(KEY, json.dumps(snapshot()), ex=300)
    except Exception as exc:
        log.debug("machine snapshot not stored: %s", str(exc)[:80])


def loop(stop, interval=45):
    while not stop.is_set():
        try:
            publish()
        except Exception as exc:
            log.warning("metrics failed: %s", str(exc)[:120])
        stop.wait(interval)
