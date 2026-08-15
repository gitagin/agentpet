# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0861 | 0.1762 | 0.4291 |
| `fts` | `fts_search` | 60 | 1.0427 | 1.6558 | 2.8383 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 6.8564 | 8.3598 | 10.9857 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.2249 | 0.5175 | 0.9264 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.2206 | 0.7105 | 1.0753 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.9087 | 2.9777 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 18.7867 | 24.1643 | 25.6416 |
| `vector` | `vector_adapter_residual` | 60 | 2.7194 | 4.6669 | 5.3655 |
| `vector` | `vector_local_search` | 60 | 9.8830 | 12.4208 | 14.5675 |
| `hybrid_rrf` | `embedding` | 60 | 0.2054 | 0.4463 | 0.6974 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1411 | 0.5174 | 2.6055 |
| `hybrid_rrf` | `fts_search` | 60 | 0.8363 | 2.2825 | 3.5787 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 18.0828 | 25.6453 | 30.0505 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 2.5095 | 3.7907 | 4.7137 |
| `hybrid_rrf` | `vector_local_search` | 60 | 8.2473 | 11.4215 | 15.0490 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.2312 | 0.4788 | 0.5122 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1591 | 0.4755 | 0.6104 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.8583 | 2.1336 | 4.6527 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0294 | 0.0563 | 0.0651 |
| `hybrid_rrf_identity_control` | `total` | 60 | 19.7965 | 25.8663 | 26.0887 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 2.8920 | 4.0570 | 4.7865 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 9.4884 | 12.6247 | 13.8925 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
