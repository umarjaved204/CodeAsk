| Model | Mode | Parsed / attempted brackets | Valid / cited | Expected file hit |
|---|---|---|---|---|
| openai/gpt-oss-120b | lenient | 31/31 (100%) | 21/31 (68%) | 5/7 (71%) |
| openai/gpt-oss-120b | strict | 1/31 (3%) | 0/1 (0%) | 0/7 (0%) |
| qwen/qwen3.8-27b | lenient | 50/50 (100%) | 53/54 (98%) | 7/7 (100%) |
| qwen/qwen3.8-27b | strict | 46/50 (92%) | 45/46 (98%) | 7/7 (100%) |

Unverified citations (lenient), by cause:
- openai/gpt-oss-120b: {'short path': 10}
- qwen/qwen3.8-27b: {'path not supplied': 1}

Fallback rule: gpt-oss lenient validity 68% vs qwen 98% -> 69% of qwen's (misses the ~80% bar; new failure modes judged from the causes above)
