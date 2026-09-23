# Field recovery tool stack v13 — missing ink · overlap · conflict

**Goal:** Raise True STP and exact accuracy without inventing ink or reopening
residual-off latency shortcuts. One taxonomy, one ordered tool ladder, stop
ladder + per-doc budget as gates.

**Evidence:** tip-overlap n20/n100 HITL (~15–22%): mostly charge policy
(`MISSING_E4`, place-shift, bleed, empty lines), then name conflict / padded ID.

---

## 1. Problem classes (mutually exclusive priority)

| Class | Meaning | Signal (examples) |
|-------|---------|-------------------|
| **MISSING_INK** | No usable shaped value in the ROI | empty Box28 + 0 lines; blank DOB crop; unshaped garbage only |
| **OVERLAP** | Same ink, rival *parses* (not two writings) | decimal place-shift `251`↔`2.51`; ×10/×100; digit-drop `13`↔`131`; bleed cents `.43`; digit-substring `86`⊂`186` |
| **CONFLICT** | Independent rivals or arithmetic gap | paddle≠rapid non-twin names; Box28 Σ ≠ lines; ID same-length digit twins |

If both OVERLAP and CONFLICT fire, treat as **OVERLAP** first (cheaper local
repair / DI corroboration), then CONFLICT agent only on remaining genuine twins.

---

## 2. Tool inventory (role-locked)

| Tool | Code | Role | May mint | Must not |
|------|------|------|----------|----------|
| Dual local OCR (paddle+rapid) | `ocr_from_geometry` / field cascade | Primary ink | E2 when independent | Sole single-line charge AUTO |
| Tess digits whitelist | `_recognize_charge_digits_only` | Confirm / fill | Local corroboration | Sole charge authority |
| Charge x-windows + early-stop | `charge_windows_for_mode` + budget early-stop | Blank vs clipped ink | — | Cap windows globally to 1 |
| Cash ruling-split | `_ruling_split_amount` / cash ruling | Printed cents vs bleed | Cash-ruling confirm | Invent dollars |
| Azure DI crop | `charge_azure_di_residual` / DOB/name DI | Strong E4 partner | `CHARGE_DI_LOCAL_CONFIRMED` | Stack after one shaped cloud |
| Claude / gpt-4o crop | `gpt4o_crop_residual` | Overlap arbitrator + empty finance | Vision E2 / line consensus | Invent third amount |
| Conflict agent | `conflict_agent` | Pick one listed rival / BOX28\|LINES | `CONFLICT_AGENT_*` | Invent amount |
| ChargeTotalAuthority | `charge_total_authority` | Single mint CLAIM_TOTAL | E6 | Mint on bleed without cash ruling |
| Line-sum authority | `line_sum_authority` | Σ lines when Box28 empty/weak | `LINE_TOTALS_*` | Single-line dual-local alone |
| Stop ladder | `cloud_stop_ladder` | Skip cloud when locals settled **safely** | — | Settle on 0-lines or place-shift vs Σ |
| Doc latency budget | `doc_latency_budget` | Soft 18s / hard 22s optional only | — | Kill unsettled charge/DOB/ID |
| React field HITL | evaluation UI | Fail-closed residual | — | — |

---

## 3. Ladders by class

### 3.1 MISSING_INK

```
dual-local ROI (+ tess digits for charge)
  → expand crop / mid-right windows (early-stop if still blank after primary+probe)
  → Azure DI crop (one cloud)
  → Claude/gpt-4o empty-finance or handwriting crop (only if DI abstained / unshaped)
  → conflict agent N/A
  → HITL
```

**Charge special:** 0 observed lines ⇒ never `LOCALS_SETTLED` skip (need DI for E4).

**DOB:** TrOCR optional under soft budget; DI/Claude for unsettled calendar.

**ID short-padded (`0000374350`):** never settle locals alone — force one vision
corroboration before SHORT_PADDED ACCEPT.

### 3.2 OVERLAP (same ink, bad parse)

```
detect twin class (place-shift | scale | digit-drop | bleed | substring)
  → prefer DI+local fuller / cash ruling-split / longer non-implausible twin
  → if still dual-shaped disagreement: ONE vision crop on the ROI
  → soup filter: CHARGE_DI_LOCAL_CONFIRMED clears substring scrap (86 vs 186)
  → BLEED_CENTS: cash ruling without requiring `$` (`25|43`) before fail-closed
  → HITL only if twins remain non-reparable
```

**Do not** stop-ladder skip when settled Box28 is place/scale-shift of line Σ
(DJJM.040 `251` vs line `2.51`).

### 3.3 CONFLICT (genuine rivals)

```
collect rival set (shaped, non-equivalent, non-soup)
  → name: require exact normalize agreement for settle; else vision crop
  → conflict agent: must pick one listed rival or BOX28|LINES or ABSTAIN
  → mint CLAIM_TOTAL / field accept only on resolve
  → ABSTAIN → HITL
```

Hard-15: digit-drop with no confirming local stays closed unless agent picks a
listed rival from the crop.

---

## 4. Gap class → recovery class map

| Gap / reason | Class | Primary tools |
|--------------|-------|---------------|
| `EMPTY_FINANCIAL_INK` | MISSING_INK | DI → gpt4o empty-finance sweep |
| `LINE_SUM_UNCORROBORATED` / `SINGLE_LINE_REQUIRES_DI` | OVERLAP or MISSING | DI/vision on line+Box28; never settle-skip on place-shift |
| `MISSING_E4` + 0 lines + dual local | MISSING_INK (policy) | Force DI for `CHARGE_DI_LOCAL_CONFIRMED` |
| `BLEED_CENTS_FAIL_CLOSED` | OVERLAP | Cash ruling-split confirm |
| `CONFLICT_MARGIN_TOO_SMALL` (charge substring) | OVERLAP | DI soup relief |
| `NAME_ENGINE_CONFLICT` / name `MISSING_E2` | CONFLICT | Vision + conflict agent |
| `SHORT_PADDED_MEMBER_ID_*` | MISSING_INK (corroboration) | Force gpt4o/DI ID crop |
| `HANDWRITING_UNREADABLE` DOB | MISSING_INK | TrOCR → DI → Claude |
| `FINANCIAL_CONFLICT_HITL` Box28≠Σ | CONFLICT | Conflict agent BOX28\|LINES |

---

## 5. Orchestration contract

Executable router: `packages/extraction_recovery/field_recovery_router.py`  
Config: `config/field_recovery_toolstack_v13.yaml`

```text
classify(field, candidates, lines, reasons)
  → FailureMode {MISSING_INK|OVERLAP|CONFLICT|NONE}
plan(mode, field, …)
  → ordered ToolStep[] (respect stop ladder + doc budget)
```

Wire points (incremental):

1. After local OCR + service lines — classify Box28/name/ID/DOB rows.
2. Residual attach (`_maybe_attach_*`) — follow plan; do not ad-hoc env spaghetti.
3. Reconciler — OVERLAP soup / bleed already authority-gated; CONFLICT margin after tools.
4. Metrics — count by FailureMode + tool fired (not only gap_class).

---

## 6. Accuracy / STP gates (honest)

| Gate | Rule |
|------|------|
| False accepts | Critical FA = 0 on agent-GT scored fields |
| Tip-overlap STP | Within 2 pp of prior tip decide on same ids after fresh OCR |
| Ops STP | Separate file; never merge with tip |
| Latency | Soft 18 / hard 22 optional only; workers=1 until locks shard |
| Invent ink | Forbidden — abstain → HITL |

---

## 7. Implementation order

1. ~~Stop-ladder exceptions (0-lines, place-shift, padded ID, name norm)~~ shipped `5c2a0fc`
2. ~~DI soup + ruling-split without `$`~~ shipped `5c2a0fc`
3. **This doc + router + config** (classification + plan)
4. Wire router into residual attach (replace scattered ifs)
5. Conflict-agent first for name CONFLICT after one vision
6. Re-run tip-overlap n20 → n100 with memory hygiene between batches

---

## 8. Non-goals

- Global residual-off / paddle-only defaults
- Softening single-line dual-local AUTO
- Multi-worker VLM until shard-safe locks
- Merging tip decide-only STP with fresh OCR ops STP
