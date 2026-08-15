# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0665 | 0.1197 | 0.2061 |
| `fts` | `fts_search` | 60 | 0.7419 | 1.7087 | 2.3961 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 5.3531 | 7.3875 | 8.0853 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.2196 | 0.4877 | 0.7966 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.2089 | 0.6944 | 0.9538 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.9228 | 1.4012 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 19.4618 | 23.7992 | 25.2854 |
| `vector` | `vector_adapter_residual` | 60 | 2.8160 | 3.7016 | 5.4239 |
| `vector` | `vector_local_search` | 60 | 9.2880 | 12.3447 | 14.4115 |
| `hybrid_rrf` | `embedding` | 60 | 0.1862 | 0.3999 | 0.4704 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1506 | 0.5013 | 0.6358 |
| `hybrid_rrf` | `fts_search` | 60 | 0.8880 | 1.9804 | 3.3886 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 17.9270 | 22.3033 | 28.1387 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 2.4194 | 3.5254 | 4.0969 |
| `hybrid_rrf` | `vector_local_search` | 60 | 8.5406 | 11.2596 | 14.1462 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1856 | 0.5362 | 1.6806 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1675 | 0.3827 | 0.5689 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.8568 | 2.1768 | 2.9566 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0289 | 0.0442 | 0.2452 |
| `hybrid_rrf_identity_control` | `total` | 60 | 18.1269 | 24.5676 | 31.5200 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 2.5474 | 4.3331 | 4.7227 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 8.6201 | 12.5595 | 17.6879 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
