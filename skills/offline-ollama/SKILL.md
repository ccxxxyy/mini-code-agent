---
name: offline-ollama
description: Guide for running Mini-Code-Agent with local Ollama in offline/intranet environments
triggers:
  - "ollama"
  - "offline"
  - "local model"
---

You are assisting a user who wants to run Mini-Code-Agent in an **offline or intranet environment** using a local LLM via Ollama.

Key facts:
- Mini-Code-Agent uses the OpenAI-compatible API format. Ollama exposes a compatible endpoint at `http://localhost:11434/v1`.
- No code changes needed -- just set environment variables or CLI args.

Setup steps to guide the user through:

1. **Install Ollama**: https://ollama.com (or internal package manager)
2. **Pull a recommended model**:
   - `ollama pull qwen2.5-coder:7b` (best balance of speed and quality for coding)
   - `ollama pull deepseek-coder-v2:16b` (stronger but slower)
   - `ollama pull codellama:13b` (Meta's coding model)
3. **Configure Mini-Code-Agent**:
   ```bash
   export OPENAI_API_KEY=ollama          # Ollama doesn't check keys, any value works
   export OPENAI_BASE_URL=http://localhost:11434/v1
   export MINI_AGENT_MODEL=qwen2.5-coder:7b
   ```
   Or via CLI: `mini --base-url http://localhost:11434/v1 --model qwen2.5-coder:7b --api-key ollama`
4. **Switch models at runtime**: use `/model <name>` to hot-swap between pulled models
5. **Verify**: run `mini` and send a simple coding task

Limitations to mention:
- Local models are weaker than cloud models (GPT-4o, DeepSeek-chat) -- expect simpler tool use
- Ollama models may not support all tool-calling features (function calling support varies by model)
- For best results, use models with explicit tool/function-calling support
