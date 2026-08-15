# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0507 | 0.0910 | 0.2245 |
| `fts` | `fts_search` | 60 | 0.5865 | 0.9289 | 1.8098 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.0479 | 4.6676 | 5.5462 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1312 | 0.2747 | 0.3394 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1096 | 0.4194 | 0.4741 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.4956 | 0.8190 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 11.7686 | 13.1496 | 13.5725 |
| `vector` | `vector_adapter_residual` | 60 | 1.6154 | 1.8921 | 2.0919 |
| `vector` | `vector_local_search` | 60 | 5.8666 | 6.6937 | 7.4459 |
| `hybrid_rrf` | `embedding` | 60 | 0.1285 | 0.2484 | 0.3610 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1046 | 0.2811 | 0.3606 |
| `hybrid_rrf` | `fts_search` | 60 | 0.6171 | 1.3302 | 1.6988 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.7045 | 15.7329 | 17.8849 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6476 | 2.3100 | 2.7584 |
| `hybrid_rrf` | `vector_local_search` | 60 | 6.0175 | 8.2869 | 8.7603 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1275 | 0.2496 | 0.3280 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.0965 | 0.2513 | 0.4251 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.5892 | 1.1093 | 2.1470 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0193 | 0.0284 | 0.0386 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.5991 | 14.3282 | 15.5231 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6228 | 2.0261 | 2.3019 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 5.9953 | 6.9382 | 7.4335 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
