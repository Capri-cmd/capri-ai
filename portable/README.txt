CAPRI // DEV BUILD
==================

Unzip anywhere, run Capri.exe. Windows 10/11, a GPU with 4-8 GB of VRAM recommended.

First run
  She starts right away. Right-click her > Brain > "Get ..." downloads a brain (and its engine);
  Ears and "Her voice" download theirs the same way. Downloads resume if your connection drops.
  Everything stays inside this folder.

Talking to her
  Click her to type. Hold Ctrl+1 to talk (change it in right-click > Ears).
  Right-click her for everything else.

Testing your own model
  Drop any .gguf into models\llm, then right-click her > Brain and pick it. It swaps live.
  Anything llama.cpp release b11932 can run works (Qwen3.5, Llama, Mistral, Gemma...).
  Thinking is switched off; the chat template comes from the GGUF.

Files
  models\llm\      brains (.gguf)          engines\    llama.cpp + whisper.cpp
  models\whisper\  ears (ggml-*.bin)        data\       her settings, memory, logs
  config.yaml      optional settings (your name, context size, temperature...)

Logs (for bug reports): data\capri.log, data\llama-server.log, data\whisper-server.log
Delete data\memory.json to wipe what she remembers.

Fan-made project. Capri and Cyberpunk: Edgerunners belong to CD PROJEKT RED.
