# TASK-1204 Retrieval Corpus Manifest

- Schema: `retrieval-eval-dataset.v1`
- Corpus version: `agent-pet-retrieval-synthetic-v1.0.0`
- Cases: 60
- Documents: 28
- Stable chunks: 120
- Distinct answerable gold sets: 22
- Random seed: 1204
- Data class: synthetic-only; no diary, chat, credential, or real Vault data
- Citation ID rule: `citation:agent-pet-retrieval-v1:<stable_chunk_id>`
- Runtime mapping: logical vault + relative path + chunk index + content hash
- Weighting: case-macro; labelled query variants may share one gold evidence set

## Frozen input hashes

| Input | SHA-256 |
| --- | --- |
| `corpus_sha256` | `7c5abc7749fd82539cb7a4a081e66eea34ac24819c73e2bb150b1931b651fe26` |
| `evaluator_sha256` | `ad387e7585980a4b5fb205af6210820489c9123947d47533feeeb0954c206ae4` |
| `configuration_sha256` | `f1bb5657936b9c1af0a36991edbe2a6ed1017034aa6cc641b3b8b0e5cdd4b0b9` |
| `production_retrieval_sha256` | `18181a51537c4ff9c97e0afc3037bca626db280be618398960a6bfd93e994cd3` |
| `production_repository_sha256` | `661dc5fb1763e3f6b3bc859a3907f6e1557ea21ca5af2ad15c2f0b56ea1cca30` |
| `production_chunker_sha256` | `1c39e45916c336e8e7c93b500bf734554f5da638217f90eb4bddb257c087071f` |
| `production_fts_schema_sha256` | `b28b8406becc65f5c12d5d4463cd1261674ca592d9da944e44dcdc80a392df13` |

## Primary slices

| Primary slice | Cases | Minimum |
| --- | ---: | ---: |
| `exact_keyword_identifier` | 10 | 10 |
| `no_ascii_keyword_overlap` | 15 | 15 |
| `chinese_conversational` | 8 | 8 |
| `cross_expression_zh_en` | 5 | 5 |
| `temporal_date_entity` | 7 | 7 |
| `contradictory_stale_superseded` | 5 | 5 |
| `permission_inactive_sensitive` | 5 | 5 |
| `empty_adversarial_unanswerable` | 5 | 5 |

The labels are visible and frozen. This is a deterministic design benchmark, not a hidden or unbiased test set.
