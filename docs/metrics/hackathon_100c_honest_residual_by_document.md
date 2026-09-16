# Honest residual HITL — Hackathon new-100 (`docs[350:450]`)

| Category | Count |
|---|---:|
| Catastrophic registration / multipage warps | **37** |
| True empty box-28 (no line ink) | **1** |
| Genuine dual-engine **ID digit** conflicts | **0** |
| Genuine dual-engine **DOB calendar** conflicts | **0** |
| Other field HITL (handwriting / calibration / fragments) | **14** |
| True STP (not HITL) | **48** |

## 1) Catastrophic registration / multipage warps

1. `Group A__M048HJDF.024` — low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
2. `Group A__M048HJDF.023` — low_inlier_ratio,low_coverage,unsafe_perspective_distortion
3. `Group A__M048HJDF.025` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
4. `Group A__M048HJDF.027` — low_inlier_ratio,unsafe_rotation
5. `Group A__M048HJDF.028` — low_coverage,unsafe_perspective_distortion
6. `Group A__M048HJDF.029` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
7. `Group A__M048HJDF.030` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
8. `Group A__M048HJDF.031` — low_inlier_ratio,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
9. `Group A__M048HJDF.033` — low_inlier_ratio,unsafe_perspective_distortion,invalid_transformed_corners
10. `Group A__M048HJDF.036` — low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion
11. `Group A__M048HJDF.037` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
12. `Group A__M048HJE5.003` — low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
13. `Group A__M048HJE5.007` — low_inlier_ratio,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
14. `Group A__M048HJE5.013` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
15. `Group A__M048HJE5.019` — insufficient_inliers,low_coverage,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
16. `Group A__M048HJE5.021` — insufficient_good_matches
17. `Group A__M048HJE5.020` — insufficient_inliers,low_inlier_ratio,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
18. `Group A__M048HJE5.027` — template_lineage_mismatch
19. `Group A__M048HJHO.001` — low_inlier_ratio,low_coverage,unsafe_perspective_distortion
20. `Group A__M048HJHO.011` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
21. `Group A__M048HJHO.014` — template_lineage_mismatch
22. `Group A__M048HJHO.015` — template_lineage_mismatch
23. `Group A__M048HJHO.017` — template_lineage_mismatch
24. `Group A__M048HJHO.016` — insufficient_inliers,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
25. `Group A__M048HJHO.018` — insufficient_inliers,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
26. `Group A__M048HJHO.019` — insufficient_inliers,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
27. `Group A__M048HJHO.021` — template_lineage_mismatch
28. `Group A__M048HJHO.020` — insufficient_inliers,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
29. `Group A__M048HJHO.022` — insufficient_inliers,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
30. `Group A__M048HJHO.027` — low_inlier_ratio,low_coverage,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
31. `Group A__M048HJHO.029` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
32. `Group A__M048HJHO.032` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
33. `Group A__M048HJHO.033` — insufficient_inliers,low_inlier_ratio,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
34. `Group A__M048HJHO.034` — low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion
35. `Group A__M048HJHO.035` — low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion
36. `Group A__M048HJHO.039` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners
37. `Group A__M048HJHO.040` — insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners

## 2) True empty box-28 with no line ink

1. `Group A__M048HJHO.025` — blockers=['insured_id_number', 'patient_dob', 'total_charge'] gaps={'insured_id_number': 'HANDWRITING_UNREADABLE', 'patient_dob': 'HANDWRITING_UNREADABLE', 'total_charge': 'EMPTY_FINANCIAL_INK'}

## 3a) Genuine dual-engine ID digit conflicts

(none)

## 3b) Genuine dual-engine DOB calendar conflicts

(none)

## Other honest field HITL

1. `Group A__M048HJDF.041` — blockers=['patient_dob'] gaps={'patient_dob': 'AMBIGUOUS_DIGIT_FRAGMENTS'}
2. `Group A__M048HJDF.044` — blockers=['patient_dob'] gaps={'patient_dob': 'AMBIGUOUS_DIGIT_FRAGMENTS'}
3. `Group A__M048HJE5.015` — blockers=['insured_id_number'] gaps={'insured_id_number': 'CALIBRATION_HITL'}
4. `Group A__M048HJE5.016` — blockers=['patient_dob'] gaps={'patient_dob': 'AMBIGUOUS_DIGIT_FRAGMENTS'}
5. `Group A__M048HJE5.018` — blockers=['patient_dob'] gaps={'patient_dob': 'CALIBRATION_HITL'}
6. `Group A__M048HJE5.023` — blockers=['insured_id_number', 'patient_name', 'patient_dob'] gaps={'insured_id_number': 'CALIBRATION_HITL', 'patient_name': 'HANDWRITING_UNREADABLE', 'patient_dob': 'HANDWRITING_UNREADABLE'}
7. `Group A__M048HJHO.002` — blockers=[] gaps={}
8. `Group A__M048HJHO.003` — blockers=['patient_dob'] gaps={'patient_dob': 'CALIBRATION_HITL'}
9. `Group A__M048HJHO.005` — blockers=['patient_dob'] gaps={'patient_dob': 'CALIBRATION_HITL'}
10. `Group A__M048HJHO.008` — blockers=['patient_dob'] gaps={'patient_dob': 'AMBIGUOUS_DIGIT_FRAGMENTS'}
11. `Group A__M048HJHO.010` — blockers=['insured_id_number'] gaps={'insured_id_number': 'CALIBRATION_HITL'}
12. `Group A__M048HJHO.012` — blockers=[] gaps={}
13. `Group A__M048HJHO.024` — blockers=['insured_id_number', 'patient_dob'] gaps={'insured_id_number': 'HANDWRITING_UNREADABLE', 'patient_dob': 'AMBIGUOUS_DIGIT_FRAGMENTS'}
14. `Group A__M048HJHO.028` — blockers=[] gaps={}
