# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0559 | 0.0850 | 0.2471 |
| `fts` | `fts_search` | 60 | 0.6090 | 1.2762 | 2.8643 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.2703 | 6.2729 | 8.3518 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1375 | 0.3074 | 0.4391 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1139 | 0.5145 | 0.5880 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.6088 | 1.0246 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.7661 | 16.0279 | 18.7126 |
| `vector` | `vector_adapter_residual` | 60 | 1.6305 | 2.8590 | 3.0535 |
| `vector` | `vector_local_search` | 60 | 5.7915 | 8.3868 | 11.1524 |
| `hybrid_rrf` | `embedding` | 60 | 0.1422 | 0.3291 | 0.3932 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1027 | 0.2638 | 0.3173 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6334 | 1.4166 | 1.7345 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.5037 | 14.7712 | 310.7806 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6269 | 2.2520 | 300.6914 |
| `hybrid_rrf` | `vector_local_search` | 60 | 5.7442 | 7.3552 | 7.4254 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1321 | 0.2322 | 0.2647 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0901 | 0.2707 | 0.3013 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.6025 | 1.1107 | 1.7765 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0187 | 0.0269 | 0.0283 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.1199 | 13.9878 | 15.5986 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6067 | 1.9755 | 2.3753 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 5.6952 | 6.5411 | 9.2258 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
