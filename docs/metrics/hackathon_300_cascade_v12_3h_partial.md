# Independent-300 v12.3h — partial latency

Config: workers=1, residuals off, `CDP_LEARNED_MATCHER=0`, name confirm min 0.80.

Progress **204/300**: mean **9.9s**, p50 **9.3s**, max **23.0s**, over_30=0.

Dispositions: {'HITL': 13, 'TRUE_STP': 144, 'REGISTRATION_FAILED': 47} (TRUE_STP=144, HITL=13, REG_FAILED=47).

vs v12.2 ops (same Independent-300 slice): v12.2 true_STP/HITL were higher-latency (~128s p50); v12.3h prioritizes ≤30s/doc mean.

Out dir: `evaluation_results/hackathon_300_cascade_v12_3h`.
