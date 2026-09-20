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

Use Python 3.11 or newer. The default installation supports offline demos and
validation without an API key, Docker, or the OpenAI SDK.

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
input. The Operator Process—not the Host CLI—chooses the
structured execution Action.

See [the design](docs/design.md), [normative semantics](docs/semantics.md),
[security model](docs/security-model.md), and
[architecture/codebase guide](docs/codebase-guide.md). The
[reference/production split](docs/reference-and-production.md) explains what
belongs here and what belongs in a separate Linux/OCI runtime implementation.

## Extended offline proof

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario extended
```

Read the JSON evidence:

| Field | Expected result | What it demonstrates |
| --- | --- | --- |
| `ipc.source_authenticated` | `true` | Kernel supplies the sender PID |
| `resource.denied.bridge_invocations` | `0` | Missing Authority prevents bridge invocation |
| `cancellation.owner_state`, `child_state` | `CANCELLED` | Cancellation follows attached ownership |
| `cancellation.child_result_publications` | `1` | One terminal result is published |
| `cancellation.late_outcome_suppressed` | `true` | Late resource completion cannot revive a Process |

The Operator chooses Actions; the Kernel authenticates identity, admits work,
and owns cleanup. HostAdmin supplies trusted root lifecycle administration.
See [the evidence and review record](docs/design-edition-validation.md).

## Optional OpenAI boundary proof

`OpenAIResponsesBackend` is an optional reference adapter showing that model
SDK types stay outside the Kernel. It is not a production-supported model
gateway. `AsyncOpenAI` reads `OPENAI_API_KEY` from the environment when no
explicit key is supplied.

Install the optional provider dependency after the default environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-openai.txt
```

```python
from semshell.llm import LLMRequest
from semshell.llm.openai import OpenAIResponsesBackend

backend = OpenAIResponsesBackend()
response = await backend.generate(
    LLMRequest(
        model="your-model-id",
        input="Describe the available process capabilities.",
    )
)
print(response.output_text)
```

The following provider checks use an injected fake client and perform no API call:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_openai_backend.py
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
```

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --exclude semshell/llm/openai.py --cache-dir .venv/.cache/mypy semshell
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
```
