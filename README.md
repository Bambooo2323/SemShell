# SemShell
SemShell — A process-centric, LLM-operated CLI runtime where LLMs, tools, and ordinary programs are equal executables.

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

See [the design](docs/design.md), [normative semantics](docs/semantics.md), and
[security model](docs/security-model.md).

## OpenAI Responses backend

`OpenAIResponsesBackend` is a user-space model adapter. It does not add LLM
semantics to the process kernel. `AsyncOpenAI` reads `OPENAI_API_KEY` from the
environment when no explicit key is supplied.

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

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
```
