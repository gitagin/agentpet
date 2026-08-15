# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0639 | 0.1239 | 0.1610 |
| `fts` | `fts_search` | 60 | 0.6190 | 1.4106 | 3.6771 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.1882 | 6.8691 | 10.2073 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1427 | 0.2559 | 0.3460 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1232 | 0.4308 | 0.4784 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.5121 | 1.0226 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 12.0321 | 15.0168 | 17.4188 |
| `vector` | `vector_adapter_residual` | 60 | 1.6686 | 2.1442 | 2.8199 |
| `vector` | `vector_local_search` | 60 | 6.0825 | 7.6745 | 9.0337 |
| `hybrid_rrf` | `embedding` | 60 | 0.1516 | 0.2839 | 0.4965 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1043 | 0.3614 | 0.4554 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6253 | 1.3991 | 2.0252 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 13.4986 | 18.4850 | 19.2289 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.7547 | 2.3889 | 3.0264 |
| `hybrid_rrf` | `vector_local_search` | 60 | 6.4994 | 8.7927 | 10.4067 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1260 | 0.2698 | 0.3132 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0949 | 0.3115 | 0.3305 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.5574 | 1.0716 | 1.9193 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0188 | 0.0292 | 0.0410 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.5618 | 14.1070 | 15.3430 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6340 | 2.0449 | 2.2717 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 6.1047 | 6.7145 | 7.3228 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
