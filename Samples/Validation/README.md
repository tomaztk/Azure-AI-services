# Validation of Information — Azure AI Foundry Demo

> **Enterprise issue: Non-Demo — Validation of Information**
>
> AI extraction pipelines produce structured data from unstructured sources.
> Without a validation layer, errors propagate silently into CRMs, BI dashboards,
> and operational reports. This project demonstrates how to catch and correct those
> errors before they cause harm.

---

## The Problem

| Without validation | With this pipeline |
|---|---|
| AI extraction runs, outputs go directly to CRM | Every record passes through 5 validation layers |
| Hallucinated summaries treated as fact | Groundedness scored against source transcript |
| Invalid taxonomy paths break downstream filters | KB lookup rejects unknown product paths |
| Sentiment contradictions go unnoticed | Rules engine + agent detect logic conflicts |
| No confidence signal for downstream systems | Every record carries a confidence score |

---

## Architecture — 5-Layer Validation Pipeline

```
  Input Record (JSON)
       │
       ▼
  ┌────────────────────────────────────────────────────────────┐
  │  Layer 1/2 · Rules Engine  (rules_engine.py)               │
  │  • Required fields present?                                 │
  │  • Summary word count in range?                             │
  │  • Sentiment scores within [-1.0, 1.0]?                     │
  │  • Sentiment label vs score direction consistent?           │
  │  • Resolution and tonality valid labels?                    │
  └────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │  Layer 3 · Knowledge-Base Lookup  (knowledge_base.py)      │
  │  • Is the L1→L2→L3 taxonomy path known?                    │
  │  • Is the service label in the KB?                         │
  └────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │  Layer 4 · AI Evaluation SDK  (evaluator.py)               │
  │  azure.ai.evaluation                                        │
  │  • GroundednessEvaluator — summary grounded in transcript? │
  │  • RelevanceEvaluator    — content relevant to call topic? │
  │  • CoherenceEvaluator    — summary coherent?               │
  └────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │  Layer 5 · Foundry Agent  (validator.py)                   │
  │  azure.ai.projects — AIProjectClient + FunctionTool        │
  │  • check_taxonomy_validity()                                │
  │  • check_service_label()                                    │
  │  • assess_internal_consistency()   ← contradiction detect  │
  │  • suggest_correction()            ← auto-correct bad fields│
  └────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
  ValidationReport → terminal + CSV
```

---

## Demo Records

The built-in demo (`--demo`) runs 6 synthetic records that each exercise a different failure mode:

| Record | Issue | Layer |
|--------|-------|-------|
| `call_001_clean.wav` | No issues — clean pass | All |
| `call_002_sentiment_error.wav` | sentiment=Positive but score=-0.80 | L1/2 |
| `call_003_bad_taxonomy.wav` | L3 "Add Named Driver" not in KB | L3 |
| `call_004_contradiction.wav` | resolution=Resolved but action=Escalated | L5 |
| `call_005_missing_fields.wav` | Missing required fields, invalid labels | L1/2 |
| `call_006_unknown_service.wav` | Service label not in KB | L3 |

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Azure values
az login
```

## Usage

```bash
# Built-in demo (6 synthetic records)
python main.py --demo

# Validate a single JSON record
python main.py --input my_record.json

# Batch validate a JSONL file (one record per line)
python main.py --input records.jsonl --batch
```

## Output

Each run appends a row to `validation_results.csv`:

```
validated_at, record_id, overall_status, confidence,
schema_error_count, rule_warning_count, kb_issue_count,
eval_issue_count, agent_finding_count, correction_count,
groundedness_score, relevance_score, coherence_score,
schema_errors, kb_issues, agent_findings, corrected_fields
```

## Connecting to Call Center Analyzer

Pipe the output of the Call Center Analyzer directly into this validator:

```python
from validator import validate_record
from analyzer import analyze_call
from transcriber import transcribe_audio

transcript = transcribe_audio(audio_path)
analysis   = analyze_call(audio_file=str(audio_path), transcript=transcript)

# Attach the raw transcript so Layer 4 can run groundedness checks
analysis["_transcript"] = transcript["full_text"]

report = validate_record(analysis)
```
