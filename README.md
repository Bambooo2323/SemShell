# SemShell

**A process-centric execution model for LLMs, tools, and ordinary programs.**

SemShell explores how to separate an Agent's decisions from the management of
execution. An LLM-backed program can choose what to do next, while a shared
Kernel manages process identity, permissions, messages, waiting, cancellation,
and results. Tools, coordinators, and human-facing shells use that same contract.

This repository is an early, executable reference design written in Python.
It includes offline demonstrations, tests, and design documentation for readers
building or studying agent runtimes. The interfaces and documentation may evolve
as the design is tried and discussed.

[Quick start](#quick-start) · [Demos](#60-second-architecture-proof) ·
[Design](docs/design.md) · [中文设计文章](SemShell_zh.md) · [MIT license](LICENSE)

## Execution model

```text
Host bootstrap → register ProcessImages → start an Operator Process
                                                │
                                      receive Event / return Action
                                                │
                                             Kernel
                                  ┌─────────────┼─────────────┐
                               spawn/wait      IPC      resource admission
                                  │             │             │
                              Processes     Processes     Host bridges
```

A `ProcessImage` defines versioned software. A `ProcessSpec` requests one
execution, and the Kernel admits it as a `Process` with a PID and effective
Authority. Each activation delivers one Event to the program and accepts one
Action in return.

An **Operator** is an ordinary Process that chooses Actions. It can be driven by
human input, deterministic rules, or an LLM. These are software roles: the Kernel
uses the same lifecycle and permission rules for all of them.

## Quick start

Clone or download this repository and open a terminal in its root directory.
Use **Python 3.11 or newer**. The default demos run offline: no API key, Docker,
or model SDK is needed. The default runtime uses the Python standard library;
`requirements.txt` installs the tools used for validation.

**Linux / macOS**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m semshell.cli.main demo --operator rule
```

**Windows / PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
```

The command prints JSON with `result` equal to `["alpha", "beta"]` and a
four-Process tree. No interactive input is required.

In the commands below, replace `python` with `.venv/bin/python` on Linux/macOS
or `.\.venv\Scripts\python.exe` on Windows. Run them from the repository root.

## 60-second architecture proof

Run the same deterministic task through three replaceable Operator Processes:

```sh
python -m semshell.cli.main demo --operator human
python -m semshell.cli.main demo --operator rule
python -m semshell.cli.main demo --operator llm
```

Each command prints structured JSON for the same Process tree:

```text
Operator Process
└── demo.coordinator
    ├── demo.echo("alpha")
    └── demo.echo("beta")
```

Only the Operator implementation changes. The Kernel, coordinator, and workers
are shared. The `human` demo receives a predefined task; it does not open an
interactive shell. The `llm` demo uses an offline scripted backend; it does not
call a live model.

The CLI is a bootstrap adapter for this demonstration: it creates the runtime,
registers images, and supplies an `OperatorTask` as the selected root Process's
input. The Operator Process chooses the structured execution Action.

## Extended offline proof

```sh
python -m semshell.cli.main demo --scenario extended
```

Read the JSON evidence:

| Field | Expected result | What it demonstrates |
| --- | --- | --- |
| `ipc.source_authenticated` | `true` | Kernel supplies the sender PID |
| `resource.denied.bridge_invocations` | `0` | Missing Authority prevents bridge invocation |
| `cancellation.owner_state`, `cancellation.child_state` | `CANCELLED` | Cancellation follows attached ownership |
| `cancellation.child_result_publications` | `1` | One terminal result is published |
| `cancellation.late_outcome_suppressed` | `true` | Late resource completion cannot revive a Process |

The Operator chooses Actions; the Kernel authenticates identity, admits work,
and owns cleanup. HostAdmin supplies trusted root lifecycle administration.
See [the evidence and review record](docs/design-edition-validation.md).

## Delegated-authority conversation

```sh
python -m semshell.cli.main demo --scenario delegation
```

A ConsoleBridge supplies a dialogue to an ordinary UserShell Process. Its
low-authority `llm1` starts two concurrent text tools and requests a separate
worker with permission to read one in-memory project report. UserShell creates
`llm2` under its own existing authority and relays the completed result.

```text
UserShell                  [permission to read the project report]
├── llm1                   [no resource permissions]
│   ├── word-count tool
│   └── character-count tool
└── llm2                   [permission to read the project report]
```

`llm2` is owned by UserShell and helps `llm1` through relayed messages. `llm1`
does not gain extra permissions or become the owner of the delegated worker.

The offline models deliberately attempt three forbidden operations: llm1 reads
the restricted report, llm1 tries to spawn a higher-authority child, and llm2
reads a different resource. The JSON report includes Kernel denial evidence,
ownership, effective permissions, and observed concurrent work. UserShell's
approval is a fixed allowlist policy, not an interactive human approval prompt.

See [the scenario and extension guide](docs/delegation-demo.md). No API key or
external resources are needed.

## Current scope

The reference implementation supports image and capability discovery, attached
Process ownership, structured IPC, explicit waiting, cascading cancellation,
exact capability/scope permissions, immutable results, and in-memory resource
bridges. The demonstrations expose these behaviors through JSON reports.

All ProcessPrograms execute inside one Python interpreter. Authority mediates
SemShell operations; it does **not** isolate untrusted Python code from the Host.
Use this implementation with trusted programs. The CLI currently runs the
demonstrations above; it is not an interactive coding agent or general shell.

Production execution, OS isolation, persistence, and deployment are outside this
repository's implementation scope. The proposed Linux/OCI runtime is described
in the [reference/production split](docs/reference-and-production.md).
See the [security model](docs/security-model.md) for the precise boundary.

## Optional OpenAI adapter

[`OpenAIResponsesBackend`](semshell/llm/openai.py) demonstrates a model-provider
boundary outside the Kernel. Installing it does not switch the CLI demos to a
live model. Applications can import it directly and supply an `LLMRequest`.

Install the optional provider dependency after the default environment:

```sh
python -m pip install -r requirements-openai.txt
```

The following provider checks use an injected fake client and perform no API call:

```sh
python -m pytest -q tests/test_openai_backend.py
python -m mypy --strict --cache-dir .venv/.cache/mypy semshell
```

## Validation

```sh
python -m ruff check --no-cache --target-version py311 semshell tests
python -m mypy --strict --exclude semshell/llm/openai.py --cache-dir .venv/.cache/mypy semshell
python -B -m pytest -q -o cache_dir=.venv/.cache/pytest
```

The tests run offline. The optional provider test is skipped when its SDK is
absent. Dated results and environment details are in the
[validation record](docs/design-edition-validation.md).

## Read and explore

| Start here | What it covers |
| --- | --- |
| [中文设计文章](SemShell_zh.md) | The motivation and execution model, in Chinese |
| [Design](docs/design.md) | Core concepts and the Event/Action contract |
| [Semantics](docs/semantics.md) | Current behavioral guarantees |
| [Codebase guide](docs/codebase-guide.md) | Source layout and implementation paths |
| [Delegation guide](docs/delegation-demo.md) | Scenario details and extension points |
| [Current checklist](devdoc/TODO.md) | Remaining work and possible improvements |
| [Development-document index](devdoc/README.md) | Working notes and historical plans |

Historical plans record earlier versions; current API guarantees live in
`docs/semantics.md`.

## Feedback and contributions

Feedback on the execution model, unclear semantics, and reproducible failures
is welcome. For a bug report, include your Python version, the command or small
example you ran, the expected behavior, and the actual output. Keep proposed
changes focused on the reference design and include relevant tests when behavior
changes. Future refinements are tracked in the [checklist](devdoc/TODO.md).

## License

[MIT](LICENSE).


## Note：This is a temporary version.