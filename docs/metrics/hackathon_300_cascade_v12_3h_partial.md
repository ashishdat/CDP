# Independent-300 v12.3h — partial latency

Config: workers=1, residuals off, `CDP_LEARNED_MATCHER=0`, name confirm min 0.80.

Progress **278/300**: mean **11.6s**, p50 **9.4s**, max **490.1s**, over_30=1.

Dispositions: {'HITL': 21, 'TRUE_STP': 193, 'REGISTRATION_FAILED': 64}.

One outlier max pulls mean slightly; p50 stays ~9.4s. ETA ~few minutes.

Out dir: `evaluation_results/hackathon_300_cascade_v12_3h`.
