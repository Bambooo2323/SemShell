# SemShell
SemShell — A process-centric, LLM-operated CLI runtime where LLMs, tools, and ordinary programs are equal executables.

This repository is an executable reference design, not a production scheduler.
The intended application architecture delegates real execution and isolation to
Linux and an OCI/container runtime instead of extending the Python Kernel into
an operating-system replacement.

SemShell explores a flattened architecture: the Kernel recognizes Processes,
capabilities, messages, authorities, and lifecycle states—not Agents, tools,
memory, or LLM roles.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 60-second architecture proof

Run the same deterministic task through three replaceable Operator Processes:

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm
```

Each command prints structured JSON for the same Process tree:

```text
Operator Process
└── demo.coordinator
    ├── demo.echo("alpha")
    └── demo.echo("beta")
```

Only the Operator image changes. The Kernel and ordinary software are shared,
and the LLM path uses an offline scripted backend.

The CLI is a bootstrap adapter for this demonstration: it creates the runtime,
registers images, and supplies an `OperatorTask` as the selected root Process's
input. The Operator Process—not the Host CLI or ControlGateway—chooses the
structured execution Action.

See [the design](docs/design.md), [normative semantics](docs/semantics.md),
[security model](docs/security-model.md), and
[architecture/codebase guide](docs/codebase-guide.md). The
[reference/production split](docs/reference-and-production.md) explains what
belongs here and what belongs in a separate Linux/OCI runtime implementation.

## Frozen OpenAI boundary proof

`OpenAIResponsesBackend` is an optional reference adapter showing that model
SDK types stay outside the Kernel. It is not a production-supported model
gateway. `AsyncOpenAI` reads `OPENAI_API_KEY` from the environment when no
explicit key is supplied.

```python
from semshell.llm import LLMRequest, OpenAIResponsesBackend

backend = OpenAIResponsesBackend()
response = await backend.generate(
    LLMRequest(
        model="your-model-id",
        input="Describe the available process capabilities.",
    )
)
print(response.output_text)
```

## Session-lived local Control proof

The frozen version 0.3 boundary proof includes a local administration REPL that
keeps one in-memory Kernel and Process Table alive for that CLI session. Its
commands use ControlGateway rather than accessing Kernel internals:

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main control
```

Try `images`, `spawn --image demo.echo@1 --input '{"value":"ok"}'`, `ps`,
`inspect 1`, `wait 1`, and `reap 1`. Replies are deterministic compact JSON;
the prompt and help text use stderr so stdout remains scriptable.

This is a Host administration interface, not an Operator Process. In
particular, it cannot issue Process IPC with a forged source PID, so external
`send` is intentionally unavailable.

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
```
