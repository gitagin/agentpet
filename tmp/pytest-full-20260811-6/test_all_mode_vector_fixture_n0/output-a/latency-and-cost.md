# TASK-1206 Latency and Cost

| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |
| --- | --- | ---: | ---: | ---: | ---: |
| `fts` | `embedding` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `filter_fusion_dedupe` | 60 | 0.0477 | 0.0965 | 0.1649 |
| `fts` | `fts_search` | 60 | 0.5940 | 1.1829 | 1.9985 |
| `fts` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `total` | 60 | 4.0389 | 5.1767 | 6.6839 |
| `fts` | `vector_adapter_residual` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `fts` | `vector_local_search` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `embedding` | 60 | 0.1420 | 0.3127 | 0.3871 |
| `vector` | `filter_fusion_dedupe` | 60 | 0.1029 | 0.4698 | 0.5949 |
| `vector` | `fts_search` | 60 | 0.0000 | 0.5957 | 0.8491 |
| `vector` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `vector` | `total` | 60 | 12.1444 | 13.7964 | 14.9090 |
| `vector` | `vector_adapter_residual` | 60 | 1.6558 | 2.1718 | 2.4485 |
| `vector` | `vector_local_search` | 60 | 6.0442 | 7.4412 | 7.5677 |
| `hybrid_rrf` | `embedding` | 60 | 0.1333 | 0.2887 | 0.3329 |
| `hybrid_rrf` | `filter_fusion_dedupe` | 60 | 0.1042 | 0.2755 | 0.3476 |
| `hybrid_rrf` | `fts_search` | 60 | 0.5856 | 1.1935 | 2.0857 |
| `hybrid_rrf` | `reranker` | 60 | 0.0000 | 0.0000 | 0.0000 |
| `hybrid_rrf` | `total` | 60 | 12.4822 | 14.1268 | 16.2322 |
| `hybrid_rrf` | `vector_adapter_residual` | 60 | 1.6308 | 1.8744 | 2.1430 |
| `hybrid_rrf` | `vector_local_search` | 60 | 5.9692 | 6.9261 | 8.1496 |
| `hybrid_rrf_identity_control` | `embedding` | 60 | 0.1470 | 0.2795 | 0.3957 |
| `hybrid_rrf_identity_control` | `filter_fusion_dedupe` | 60 | 0.1079 | 0.3196 | 0.5634 |
| `hybrid_rrf_identity_control` | `fts_search` | 60 | 0.5804 | 1.2481 | 1.9549 |
| `hybrid_rrf_identity_control` | `reranker` | 60 | 0.0225 | 0.0338 | 0.0882 |
| `hybrid_rrf_identity_control` | `total` | 60 | 12.8087 | 17.0550 | 19.0737 |
| `hybrid_rrf_identity_control` | `vector_adapter_residual` | 60 | 1.6759 | 2.4776 | 3.2789 |
| `hybrid_rrf_identity_control` | `vector_local_search` | 60 | 6.2069 | 7.9219 | 10.2589 |

## External use

Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.
