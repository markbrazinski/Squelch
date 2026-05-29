# squelch-harness

Adversarial eval harness for Splunk detections. Measures precision, recall, and label stability — without requiring the Squelch agent, an LLM, or any cloud services.

Part of the [Squelch](https://github.com/markbrazinski/Squelch) project.

## Install

```bash
pip install squelch-harness
```

Requires a running Splunk instance and `splunk-sdk`.

## What it does

Given a detection SPL and a labeled notable index, the harness:

1. **Evaluates** precision and recall before and after a proposed filter
2. **Clusters** false positives by field to surface the dominant pattern
3. **Attack-injects** synthetic true positives to test filter safety
4. **Perturbs** labels (10% flip, 3 trials) to check stability under noise
5. **Temporal holdout** (70/30 split) to check for overfitting

## Quick start

```python
import splunklib.client as client
from squelch_harness import evaluate_detection, cluster_fps

svc = client.connect(host="localhost", port=8089,
                     username="admin", password="changeme",
                     scheme="https", verify=False)

# Evaluate a detection
result = evaluate_detection(
    service=svc,
    detection_name="DNS_TunnelExfil_Heuristic",
    detection_spl='search index=notable search_name="DNS_TunnelExfil_Heuristic"',
    golden_query='search index=notable sourcetype=squelch_notable',
    earliest="-30d", latest="now",
)
print(f"precision: {result.precision:.2%}, recall: {result.recall:.2%}")

# Cluster FPs to find the dominant pattern
events = [...]  # list of event dicts from your notable index
clusters = cluster_fps(events, fields=("src_ip", "dest", "user"))
print(clusters.winner)
```

## Bundled lookups

The package ships three reference lookups used by the Squelch demo:

- `disposition_normalization.csv` — maps 6 SOC label formats to `true_positive`/`false_positive`
- `scanner_ips.csv` — known vulnerability scanner IPs
- `service_accounts.csv` — known service accounts

```python
from pathlib import Path
import squelch_harness
lookups_dir = Path(squelch_harness.__file__).parent / "lookups"
```

## License

MIT
