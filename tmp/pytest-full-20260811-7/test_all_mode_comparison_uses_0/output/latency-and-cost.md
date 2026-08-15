# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0576 | 0.1394 | 0.1719 |
| `fts` | `fts_search` | 60 | 0.6653 | 1.4195 | 1.8665 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.5697 | 5.9391 | 6.8887 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1354 | 0.2941 | 0.3794 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1041 | 0.4279 | 0.5542 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.4945 | 0.8354 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.8522 | 14.0521 | 16.6244 |
| `vector` | `vector_adapter_residual` | 60 | 1.6608 | 2.0839 | 2.2449 |
| `vector` | `vector_local_search` | 60 | 5.8656 | 7.3195 | 8.5734 |
| `hybrid_rrf` | `embedding` | 60 | 0.1357 | 0.2849 | 0.3420 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1066 | 0.2929 | 0.3692 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6166 | 1.1996 | 1.8412 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.4101 | 15.8290 | 391.9116 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6443 | 2.1852 | 377.7015 |
| `hybrid_rrf` | `vector_local_search` | 60 | 5.8859 | 8.0244 | 8.6034 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1602 | 0.2893 | 0.3806 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0976 | 0.3401 | 0.4234 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6516 | 1.2315 | 1.7198 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0216 | 0.0330 | 0.1318 |
| `hybrid_rrf_identity_control` | `total` | 60 | 13.9492 | 18.3735 | 20.7033 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.8109 | 2.7139 | 3.1096 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 6.3343 | 9.6063 | 10.9690 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
