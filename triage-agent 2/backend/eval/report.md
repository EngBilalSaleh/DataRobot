# Evaluation report

Mode: openai/gpt-oss-20b / openai/gpt-oss-120b. Embeddings: fastembed. Gate threshold: 0.85. Tickets: 40.

| Metric | Result |
|---|---|
| Routing accuracy (queue) | 78% (31/40) |
| Intent accuracy | 90% (36/40) |
| Routing accuracy, English | 75% (18/24) |
| Routing accuracy, Arabic | 81% (13/16) |
| Sent automatically | 45% (18/40) |
| Precision of auto-sent tickets (correct queue) | 56% (10/18) |
| Risky tickets held for review | 100% (9/9) |
| Drafts fully grounded in real sources | 100% (40/40) |
| Median seconds per ticket | 14.885 |
| Errors | 0 |

Precision of auto-sent tickets matters more than the auto-send rate: raise GATE_THRESHOLD
until it is where the customer wants it, and accept that fewer tickets go out automatically.
