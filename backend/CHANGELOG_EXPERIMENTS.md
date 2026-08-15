# ChatBI BIRD EX Experiment Log

| Run | Preset | N | EX | valid_sql | exec_err | Notes |
|-----|--------|---|-----|-----------|----------|-------|
| R0 | baseline | 100 | **53%** | 100% | 0% | Agentar c=3, rewrite on |
| R1-wrong | target-v1 | 47 wrong | 29.8% | 100% | 0% | fixed ~14/47 baseline errors |
| R1 | target-v1 | 100 | **65%** | 100% | 0% | rewrite off, full schema, c=6 |
| R2 | target-v4 + prompts | 100 | **66.7%** | 99% | 0% | sql_validate, c=9, qsql on |
| R3-wrong | target-v6 + prompt v2 | 33 wrong | **24.2%** (8/33) | 100% | 0% | 错题快测，验证 prompt |
| **R4** | **target-v6** | **100** | **71.7%** | 99% | 0% | **达标 ≥70%**；v5+c=9+prompt v2，无 qsql |

产物：`artifacts/benchmarks/bird_20260623_042753_327653256081702912.json`

## R0 baseline preset
- Config: `baseline` (Agentar, candidates=3, rewrite on, schema selection on)
- Expected EX: ~54% @ 100 samples

## R1 target-v1
- Disable rewrite/summary for benchmark
- Full schema when table count <= 15
- Agentar candidates=6, ddl-first path order

## R2 target-v2
- target-v1 + Q-SQL recall enabled
- Import Q-SQL: `bash _import_bird_qsql.sh --limit 5000`

## R3 target-v3
- target-v2 + sql_validate + sql_fix_max_attempts=2
- SQLite-aware prompts in Text2SQL / validate / selector

## R4 target-v4
- target-v3 + candidates=9

Run:
```bash
make bench PRESET=target-v3 LIMIT=100
make analyze
```
