#!/usr/bin/env python3
"""Seed `index=notable` with synthetic FP/TP-labelled events.

Bundle 3 Sessions 19-20: per-detection FP patterns. Each detection's FPs
follow one of three shapes:

  scanner_ip       — 78% draw from SCANNER_IPS pool (Bundle 1/2 behavior)
  service_account  — 65% set user="svc_backup" (Detection 2)
  extraction_gap   — 45% set dest_ip="" + sourcetype_tag="svc_install_log"
                     (Detection 3 — no dominant single-field cluster)

DNS/WindowsAuth/PortScan and the three low-FP detections keep scanner_ip.
DETECTION_FP_PATTERNS below is the single source of truth for both the
per-detection FP rate and the FP shape.

Run:
    python scripts/seed_notable.py --count 1000 --clear-first

Env (from .env at repo root):
    SPLUNK_HOST, SPLUNK_PORT, SPLUNK_ADMIN_USER, SPLUNK_ADMIN_PASSWORD
"""

import argparse
import os
import random
import sys
import time
from pathlib import Path

import splunklib.client as splunk_client


SCANNER_IPS = ["10.0.1.50", "10.0.1.51", "10.0.1.52"]

# Bundle 2 Sessions 11-12: noisy `status_label` values that look like a
# real SOC's notable index. TPs don't get creative mislabels — they're
# either `true_positive` or unlabeled. FPs are spread across 6 formats
# per spec, with a small share also unlabeled.
_FP_LABEL_CHOICES = (
    "false_positive",
    "resolved",
    "closed",
    "fp",
    "FP - scanner",
    "",
)
_FP_LABEL_WEIGHTS = (40, 16, 14, 10, 10, 10)
_BLANK_ALL_RATE = 0.20  # share of *all* events (TP or FP) with no label

# svc_backup is FP-exclusive for Identity_PrivEscalation_Confirmed. Keep
# it out of the TP user pool so the single-value bypass in Sessions 21-22
# is safe.
_TP_USER_POOL = ("alice", "bob", "carol", "dave", "svc-jenkins")
_FP_USER_POOL_GENERIC = ("alice", "bob", "carol", "dave", "svc-jenkins")
_EXTRACTION_GAP_SOURCETYPES = ("winsec", "wineventlog", "iis", "syslog")


def _pick_status_label(is_fp: bool) -> str:
    """Two-stage draw matching the Bundle 2 spec distribution.

    1. 20% of all events get blanked regardless of TP/FP ("analyst never
       looked at it").
    2. FPs that survive step 1 draw from 6 weighted formats, one of which
       is itself a blank (per-FP 10% blank share).
    3. TPs that survive step 1 are always `true_positive` — analysts
       don't mislabel TPs creatively, they just sometimes skip them.
    """
    if random.random() < _BLANK_ALL_RATE:
        return ""
    if is_fp:
        return random.choices(_FP_LABEL_CHOICES, weights=_FP_LABEL_WEIGHTS, k=1)[0]
    return "true_positive"


# (search_name, rule_name, urgency). FP rate now lives in
# DETECTION_FP_PATTERNS below — single source of truth.
DETECTIONS = [
    ("WindowsAuth_AnomalousLogonSource", "WindowsAuth_AnomalousLogonSource", "medium"),
    ("Network_PortScan_Detected",       "Network_PortScan_Detected",       "low"),
    ("DNS_TunnelExfil_Heuristic",       "DNS_TunnelExfil_Heuristic",       "high"),
    ("Web_SuspiciousUserAgent",         "Web_SuspiciousUserAgent",         "low"),
    ("Process_RareParentChild",         "Process_RareParentChild",         "medium"),
    ("Endpoint_NewServiceInstalled",    "Endpoint_NewServiceInstalled",    "medium"),
    ("Identity_PrivEscalation_Confirmed", "Identity_PrivEscalation_Confirmed", "critical"),
    ("Data_BulkDownload_Sensitive",     "Data_BulkDownload_Sensitive",     "high"),
]

DETECTION_FP_PATTERNS = {
    # Demo detections (Bundle 3)
    "DNS_TunnelExfil_Heuristic":         {"fp_rate": 0.71, "pattern": "scanner_ip"},
    "Identity_PrivEscalation_Confirmed": {"fp_rate": 0.72, "pattern": "service_account"},
    "Endpoint_NewServiceInstalled":      {"fp_rate": 0.72, "pattern": "extraction_gap"},
    # Pipeline workhorses — scanner_ip preserved from Bundle 2
    "WindowsAuth_AnomalousLogonSource":  {"fp_rate": 0.83, "pattern": "scanner_ip"},
    "Network_PortScan_Detected":         {"fp_rate": 0.74, "pattern": "scanner_ip"},
    "Web_SuspiciousUserAgent":           {"fp_rate": 0.34, "pattern": "scanner_ip"},
    "Process_RareParentChild":           {"fp_rate": 0.27, "pattern": "scanner_ip"},
    "Data_BulkDownload_Sensitive":       {"fp_rate": 0.03, "pattern": "scanner_ip"},
}


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'").strip('"')
        os.environ.setdefault(k, v)


def _random_internal_ip() -> str:
    return f"10.{random.randint(20, 200)}.{random.randint(0, 254)}.{random.randint(0, 254)}"


def _random_192_ip() -> str:
    return f"192.168.{random.randint(0, 254)}.{random.randint(0, 254)}"


def _apply_tp_defaults(event: dict) -> None:
    event["src_ip"] = _random_internal_ip()
    event["user"] = random.choice(_TP_USER_POOL)
    event["dest_ip"] = _random_internal_ip()
    event["sourcetype_tag"] = random.choice(_EXTRACTION_GAP_SOURCETYPES)
    event["disposition"] = random.choice([
        "TP: confirmed lateral movement",
        "TP: credential abuse",
        "TP: suspicious external exfil",
    ])


def _fp_scanner_ip(event: dict) -> None:
    if random.random() < 0.78:
        event["src_ip"] = random.choice(SCANNER_IPS)
        event["disposition"] = "FP: scanner noise"
    else:
        event["src_ip"] = _random_192_ip()
        event["disposition"] = random.choice([
            "FP: known maintenance window",
            "FP: legitimate admin activity",
            "FP: business-hours batch job",
        ])
    event["user"] = random.choice(_FP_USER_POOL_GENERIC)
    event["dest_ip"] = _random_internal_ip()
    event["sourcetype_tag"] = random.choice(_EXTRACTION_GAP_SOURCETYPES)


def _fp_service_account(event: dict) -> None:
    if random.random() < 0.65:
        event["user"] = "svc_backup"
        event["disposition"] = "FP: known service account activity"
    else:
        event["user"] = random.choice(_FP_USER_POOL_GENERIC)
        event["disposition"] = random.choice([
            "FP: known maintenance window",
            "FP: legitimate admin activity",
            "FP: business-hours batch job",
        ])
    # No scanner IPs: this detection's clustering must not surface them.
    event["src_ip"] = _random_192_ip()
    event["dest_ip"] = _random_internal_ip()
    event["sourcetype_tag"] = random.choice(_EXTRACTION_GAP_SOURCETYPES)


def _fp_extraction_gap(event: dict) -> None:
    if random.random() < 0.45:
        event["dest_ip"] = ""
        event["sourcetype_tag"] = "svc_install_log"
        event["disposition"] = "FP: extraction gap"
    else:
        event["dest_ip"] = _random_internal_ip()
        event["sourcetype_tag"] = random.choice(_EXTRACTION_GAP_SOURCETYPES)
        event["disposition"] = random.choice([
            "FP: known maintenance window",
            "FP: legitimate admin activity",
            "FP: business-hours batch job",
        ])
    event["src_ip"] = _random_192_ip()
    event["user"] = random.choice(_FP_USER_POOL_GENERIC)


_FP_PATTERN_DISPATCH = {
    "scanner_ip":      _fp_scanner_ip,
    "service_account": _fp_service_account,
    "extraction_gap":  _fp_extraction_gap,
}


def _gen_event(detection, now_unix: int) -> dict:
    search_name, rule_name, urgency = detection
    pattern_cfg = DETECTION_FP_PATTERNS[search_name]
    is_fp = random.random() < pattern_cfg["fp_rate"]
    status_label = _pick_status_label(is_fp)

    event = {
        "search_name": search_name,
        "rule_name": rule_name,
        "urgency": urgency,
        "status_label": status_label,
        "owner": random.choice(["analyst1", "analyst2", "analyst3"]),
        "dest": f"10.50.{random.randint(0, 50)}.{random.randint(0, 254)}",
        "_time": now_unix - random.randint(0, 30 * 86400),
    }
    if is_fp:
        _FP_PATTERN_DISPATCH[pattern_cfg["pattern"]](event)
    else:
        _apply_tp_defaults(event)
    return event


def _event_to_kv_string(event: dict) -> str:
    # Leading epoch timestamp parsed by props.conf TIME_PREFIX=^ TIME_FORMAT=%s
    parts = [str(event["_time"])]
    for k, v in event.items():
        if k == "_time":
            continue
        v_str = str(v).replace('"', '\\"')
        parts.append(f'{k}="{v_str}"')
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000, help="total events to seed")
    parser.add_argument("--index", default="notable")
    parser.add_argument("--sourcetype", default="squelch_notable")
    parser.add_argument("--clear-first", action="store_true",
                        help="Delete existing events in the index before seeding")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    _load_env(repo_root / ".env")
    user = os.environ.get("SPLUNK_ADMIN_USER")
    pw = os.environ.get("SPLUNK_ADMIN_PASSWORD")
    host = os.environ.get("SPLUNK_HOST", "localhost")
    port = int(os.environ.get("SPLUNK_PORT", "8089"))
    if not (user and pw):
        print("error: SPLUNK_ADMIN_USER / SPLUNK_ADMIN_PASSWORD missing from .env", file=sys.stderr)
        return 1

    service = splunk_client.connect(
        host=host, port=port, username=user, password=pw,
        scheme="https", verify=False, autologin=True,
    )

    if args.clear_first:
        print(f"clearing existing events from index={args.index}...")
        job = service.jobs.create(
            f'search index={args.index} | delete',
            earliest_time='-90d', latest_time='now',
        )
        while not job.is_done():
            time.sleep(0.5)
        # `| delete` requires the `can_delete` capability; without it, the
        # job completes silently with 0 results and the index keeps stale
        # data. Surface that failure loudly — silent stacking of cohorts
        # broke Bundle 2 Session 11-12 once already.
        msgs = job.content.get("messages") or {}
        fatal = msgs.get("fatal") or msgs.get("error") or []
        if fatal:
            print(f"  delete FAILED: {fatal[0]}", file=sys.stderr)
            print(f"  hint: grant the `can_delete` capability to your role "
                  f"(Settings → Roles → admin → Capabilities → can_delete).",
                  file=sys.stderr)
            return 2
        print(f"  delete job done (events removed: {job['eventCount']})")

    index = service.indexes[args.index]
    now_unix = int(time.time())
    per_detection = args.count // len(DETECTIONS)
    actual = 0
    start = time.time()
    for detection in DETECTIONS:
        for _ in range(per_detection):
            event = _gen_event(detection, now_unix)
            index.submit(
                _event_to_kv_string(event),
                sourcetype=args.sourcetype,
                host="squelch-seed",
                source="seed_notable.py",
            )
            actual += 1
    elapsed = time.time() - start
    print(f"submitted {actual} events to index={args.index} in {elapsed:.1f}s "
          f"({actual / elapsed:.0f} events/sec)")
    print("note: events may take 5-15s to be searchable after submit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
