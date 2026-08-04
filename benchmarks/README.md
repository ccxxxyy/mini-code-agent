# Benchmark Results 评测结果


**Mini Agent Model**: deepseek-v4-flash-0731


| Task | Category | Result | Tokens | Cost | Tools | Iterations | Time |
|---|---|---|---|---|---|---|---|
| add_error_handling | feature | ✅ | 8615 | $0.0002 | 5 | 5 | 8.1s |
| add_function | feature | ✅ | 6172 | $0.0002 | 3 | 4 | 6.0s |
| create_file | feature | ✅ | 2599 | $0.0001 | 1 | 2 | 2.3s |
| find_bug | bugfix | ✅ | 6177 | $0.0002 | 4 | 4 | 5.8s |
| fix_syntax_error | bugfix | ✅ | 5612 | $0.0001 | 3 | 4 | 6.0s |
| grep_and_report | search | ✅ | 6488 | $0.0002 | 5 | 4 | 6.5s |
| multi_step_edit | feature | ✅ | 9014 | $0.0002 | 9 | 5 | 8.5s |
| read_and_summarize | search | ✅ | 4195 | $0.0001 | 2 | 3 | 3.5s |
| refactor_rename | refactor | ✅ | 6625 | $0.0002 | 5 | 4 | 6.9s |
| write_unit_test | test | ✅ | 6543 | $0.0002 | 3 | 4 | 8.2s |

## Summary 汇总

- **Mini pass rate**: 10/10
- **Total tokens**: 62040
- **Total cost**: $0.0015
- **Avg tokens/task**: 6204
- **Avg cost/task**: $0.0002
- **Total tool calls**: 40
