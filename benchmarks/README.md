# Benchmark Results 评测结果


**Mini Agent Model**: deepseek-v4-flash-0731


| Task | Category | Result | Runs | Tokens | Cost | Tools | Iterations | Time | TTFT p95 |
|---|---|---|---|---|---|---|---|---|---|
| add_error_handling | feature | ✅ | 3/3 | 15686 | $0.0004 | 4 | 4 | 8.4s | 1860ms |
| add_function | feature | ✅ | 3/3 | 15674 | $0.0004 | 4 | 4 | 8.8s | 8423ms |
| conflicting_constraints | feature | ✅ | 3/3 | 16375 | $0.0004 | 4 | 4 | 10.5s | 1371ms |
| create_file | feature | ✅ | 3/3 | 7457 | $0.0002 | 1 | 2 | 5.3s | 2258ms |
| create_from_tests | feature | ✅ | 3/3 | 16240 | $0.0004 | 4 | 4 | 9.8s | 1788ms |
| find_bug | bugfix | ✅ | 3/3 | 15426 | $0.0004 | 4 | 4 | 9.2s | 2371ms |
| fix_syntax_error | bugfix | ✅ | 3/3 | 15000 | $0.0004 | 3 | 4 | 7.9s | 1727ms |
| grep_and_report | search | ✅ | 3/3 | 16438 | $0.0004 | 6 | 4 | 14.2s | 1431ms |
| hidden_dependency_bug | bugfix | ✅ | 3/3 | 29883 | $0.0007 | 7 | 6 | 14.6s | 1548ms |
| infer_convention | feature | ✅ | 3/3 | 20442 | $0.0005 | 5 | 5 | 11.6s | 1690ms |
| large_file_navigation | bugfix | ✅ | 3/3 | 23648 | $0.0006 | 5 | 5 | 10.6s | 1743ms |
| multi_step_edit | feature | ✅ | 3/3 | 21012 | $0.0005 | 9 | 5 | 12.1s | 1783ms |
| read_and_summarize | search | ✅ | 3/3 | 11547 | $0.0003 | 2 | 3 | 6.7s | 1595ms |
| refactor_rename | refactor | ✅ | 3/3 | 20937 | $0.0005 | 7 | 5 | 11.4s | 1734ms |
| three_bugs | bugfix | ✅ | 3/3 | 51826 | $0.0013 | 13 | 9 | 30.5s | 1846ms |
| write_unit_test | test | ✅ | 3/3 | 37394 | $0.0009 | 6 | 7 | 34.5s | 2945ms |

## Summary 汇总

- **Mini passed all runs**: 16/16
- **Total tokens**: 334985
- **Total cost**: $0.0084
- **Avg tokens/task**: 20936
- **Avg cost/task**: $0.0005
- **Cost per solved task**: $0.0005
- **Total tool calls**: 84

### Reliability 可靠性 (k=3, 48 runs)

- **pass@1**: 1.000 — mean per-run success rate 单次成功率均值
- **pass^3**: 1.000 — solved in EVERY run 每次都成功的任务占比
- **rho^3**: 1.000 — consistency (1.0 = fully stable) 一致性比
- **Censored runs**: 0 — hit the iteration cap; censored samples, not failures on the merits 触顶删失样本，非实力失败

### Latency 延迟（worst across tasks 跨任务最差）

- **TTFT max**: 8423ms
- **Event-loop lag max**: 65.1ms (>100ms means the loop was blocked >100ms 即事件循环被阻塞)
