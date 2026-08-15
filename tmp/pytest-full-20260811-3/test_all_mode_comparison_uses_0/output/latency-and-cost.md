# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0758 | 0.2651 | 0.6085 |
| `fts` | `fts_search` | 60 | 0.8294 | 1.8255 | 3.1790 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 5.8532 | 8.5119 | 495.1575 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1753 | 0.4187 | 0.5075 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1712 | 0.6041 | 0.8495 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.7561 | 1.0377 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 16.0302 | 24.0629 | 27.5876 |
| `vector` | `vector_adapter_residual` | 60 | 2.1377 | 3.4337 | 6.3132 |
| `vector` | `vector_local_search` | 60 | 7.9806 | 11.9725 | 13.4997 |
| `hybrid_rrf` | `embedding` | 60 | 0.2141 | 0.4024 | 0.4891 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1613 | 0.5867 | 0.6831 |
| `hybrid_rrf` | `fts_search` | 60 | 0.9096 | 2.1517 | 3.6945 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 18.4037 | 24.1087 | 25.1438 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 2.5064 | 3.4274 | 4.3591 |
| `hybrid_rrf` | `vector_local_search` | 60 | 9.0809 | 11.2102 | 14.1876 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.2337 | 0.5411 | 0.6230 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1746 | 0.4798 | 0.7224 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 1.0810 | 2.7369 | 4.4649 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0331 | 0.0555 | 0.0761 |
| `hybrid_rrf_identity_control` | `total` | 60 | 22.4680 | 28.2763 | 32.5377 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 2.9891 | 4.6119 | 5.1017 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 10.1783 | 14.4356 | 16.3311 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
