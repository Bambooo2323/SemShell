# SemShell Architecture and Codebase Guide

This guide maps the active design-edition source tree. Normative behavior is in
[semantics.md](semantics.md).

## Architecture

```text
Demo CLI -> trusted bootstrap -> HostAdmin -> ProcessKernel
                                resources -> ResourceRegistry

ProcessProgram -> Event/Action ABI -> ProcessKernel -> ProcessResult
```

The Kernel owns Process identity, attached ownership, scheduling, lifecycle,
IPC, admission authority, and resource invocation. Human, Rule, and LLM
Operators are ordinary ProcessPrograms; the Kernel contains no role-specific
branches.

`HostAdmin` is a small trusted lifecycle facade. It has no PID and cannot
originate Process IPC. The active CLI only bootstraps and renders the offline
demonstrations. The former Control protocol and REPL are recoverable at Git tag
`complete-reference-20260915`, but are not active APIs.

## Source map

### `semshell/kernel/`

- `actions.py` defines the closed guest Action union.
- `events.py` defines mailbox and continuation Events.
- `process.py` defines public lifecycle values and snapshots.
- `_runtime.py` contains private control blocks and Kernel-owned task records.
- `kernel.py` implements admission, scheduling, IPC, attached-tree cancellation,
  waiting, resources, result publication, inspection, and shutdown.

There is no active `kernel.operations` module. Trusted callers use typed Kernel
methods; guest programs use Event/Action values.

### `semshell/software/` and `semshell/security/`

Software modules define immutable images, the reduced ProcessSpec, the Catalog,
and ProcessProgram. Security modules define Principal, exact Permission scopes,
admission policy, and explainable decisions. Policy applies caller, system,
image, and execute-ACL ceilings without silently reducing requested Authority.

### `semshell/resources/`

- `types.py` defines binding and invocation values plus payload-free audit data.
- `bridge.py` defines the passive HostResourceBridge boundary.
- `registry.py` binds trusted descriptors before Kernel startup.
- `memory.py` contains portable `read_text` validation and the deterministic
  InMemoryResourceBridge.

No active resource implementation accesses the local filesystem. The Kernel
derives PID, Principal, Authority, and invocation ID.

### `semshell/host/`

- `admin.py` exposes start, root spawn, inspect, tree, wait, cancel, and stop
  without manufacturing Process identity.
- `console.py` binds one trusted Host input source to one Process PID.

### Operators, examples, and CLI

`semshell/shells/` contains replaceable Human, Rule, and LLM Operators using one
ABI. `semshell/llm/` exports provider-neutral values and the offline scripted
backend. Optional adapters are imported from their provider module directly.

- `examples/architecture_demo.py` proves equivalent Operator fan-out/fan-in.
- `examples/extended_demo.py` proves IPC provenance, authority denial,
  attached-tree cancellation, and late-result suppression.
- `examples/reporting.py` projects only explicit demo reports to JSON.
- `examples/resource_demo.py` uses a supplied resource bridge.
- `cli/main.py` selects and renders only the offline demonstrations.

## Important paths

```text
mailbox Event -> ProcessProgram.handle() -> one Action
              -> Kernel commit -> continuation Event or ProcessResult

ProcessSpec -> Catalog -> ACL/exact Authority -> factory -> PID -> Started

InvokeResource -> binding/Permission -> frozen invocation -> bridge
               -> continuation or suppressed late result

trusted bootstrap -> HostAdmin -> ProcessKernel lifecycle method
```

## Executable evidence

- `test_kernel.py` and `test_kernel_lifecycle.py` cover scheduling and lifecycle.
- `test_authority_policy.py` and `test_catalog.py` cover policy and resolution.
- Resource tests cover portable validation, denial, capacity, cancellation, and
  late-result suppression using the in-memory bridge.
- `test_host_admin.py` verifies the Host-versus-Process identity boundary.
- Operator and demo tests verify primary and extended offline reports.
- `test_guest_abi_architecture.py` rejects guest imports of removed Control
  modules.

## Placement rules

- Generic lifecycle machinery belongs in `kernel/` only when every Process role
  needs it; executable strategies belong in guest programs.
- Host facilities cross scoped resource bridges; active proofs stay in-memory.
- Trusted root lifecycle calls go through `HostAdmin`.
- Provider SDK values are normalized before reaching guest or Kernel types.
- Production transports, filesystems, persistence, and containment belong in
  the separate Linux/OCI runtime.

## Validation

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario extended
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --exclude semshell/llm/openai.py --cache-dir .venv/.cache/mypy semshell
```
