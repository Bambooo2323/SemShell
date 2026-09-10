# SemShell Architecture and Codebase Guide

This document explains the implemented architecture through version 0.3 and
maps each source file to its responsibility. It is an onboarding guide, not a
replacement for the normative rules in [semantics.md](semantics.md).

## 1. What SemShell is

SemShell is a small process-centric semantic runtime hosted by Python and the
existing operating system. Its central design choice is to flatten LLMs,
deterministic tools, coordinators, memory-like services, and human-facing
operators into replaceable software running through one Process abstraction.

The Kernel does not contain Agent, tool, planner, or LLM roles. It knows only:

- immutable software images and single-use process specifications;
- admitted Processes with PIDs, mailboxes, ownership, and lifecycle state;
- Events delivered to programs and Actions returned to the Kernel;
- exact Principal and Authority values;
- generic Host resource invocations;
- public observation and lifecycle operations.

This is primarily an engineering and management model. It does not claim to be
a high-performance scheduler or a security boundary for untrusted Python code.

## 2. The five architectural areas

```text
Local terminal -> CLI adapter -> ControlGateway --------> ProcessKernel
                                                            |
Host resources <-> Resource bridge <-------------------------+

Model provider -> SemanticBackend -> LLMShell Process --+
Other guest ProcessPrograms ----------------------------+-> shared Event/Action ABI
                                                              <-> ProcessKernel
```

The diagram shows semantic relationships, not isolation. Kernel, bridges,
backends, and guest ProcessPrograms currently share one trusted Python process;
the “guest” label identifies protocol position, not an enforced security
boundary.

### 2.1 Kernel

The Kernel owns authentic process identity and all mutable Process/lifecycle
state. Control sessions, CLI adapters, and provider backends may own their own
boundary-local state, but none may mutate the Process Table directly. It
admits software, schedules one Event at a time, applies returned Actions,
manages ownership and waiting, resolves cancellation races, and publishes one
terminal ProcessResult per Process.

### 2.2 Guest software

A ProcessProgram is guest software. HumanShell, RuleShell, LLMShell, echo,
coordinators, and workspace-reader all implement the same `handle(context,
event) -> action` contract. Their differences are software policy, not Kernel
entity types.

### 2.3 Host resources

Resource bridges expose selected Host facilities through generic binding and
invocation values. The Kernel authenticates the caller and checks exact
binding-scoped Authority before calling a bridge. The current proof implements
bounded read-only text access through interchangeable in-memory and local
workspace bridges.

### 2.4 External Control

Control is a Host administration and observation protocol. A ControlSession has
authenticated Principal and Authority, request IDs, capacity, interruption,
and one-shot replies, but it has no PID or mailbox. Therefore it cannot
originate Process IPC or act as an Operator.

### 2.5 CLI

The version 0.3 CLI is a local adapter over ControlGateway. It parses text into
typed operations and renders public reply values as deterministic JSON. It
keeps one runtime alive across commands but does not bypass ControlGateway.

### 2.6 Boundary comparison

| Interface | Caller identity | Request form | Completion form | Intended use |
| --- | --- | --- | --- | --- |
| Event/Action ABI | admitted Process PID and context | ProcessAction from `handle()` | ProcessEvent or ProcessResult | normal guest execution |
| Resource bridge | Kernel-authenticated Process invocation | InvokeResource Action | ResourceCompleted/Rejected Event | scoped Host facilities |
| Control protocol | ControlSession Principal and Authority; no PID | ControlRequest | exactly one ControlReply | Host administration and observation |

Mutating Control operations are individually authorized. The local reference
session receives `control.process.cancel`, `control.process.reap`, and
`control.catalog.unregister`; command payloads cannot add them.
| CLI adapter | local terminal using one ControlSession | parsed typed Control operation | deterministic JSON | local Control interface |
| ConsoleBridge | trusted Host binding fixed to one PID | principal-attributed input | ConsoleInput Event | input device for one shell Process |

“Action” is shorthand for a member of the `ProcessAction` union. Each activation
returns exactly one such value; Action batches are not implemented.

## 3. Core value flow

```text
ProcessImage + ProcessSpec
          |
          v
   admission and policy
          |
          v
 ProcessContext + initial Started Event
          |
          v
 ProcessProgram.handle(context, event)
          |
          v
      ProcessAction
          |
          v
 Kernel state transition / side effect / continuation Event
          |
          v
 immutable ProcessResult
```

`ProcessImage` is the reusable definition. `ProcessSpec` is one request to run
it. A Process is the admitted runtime instance; it is represented publicly by
ProcessContext, ProcessSnapshot, and ProcessResult, while its mutable control
block remains private to the Kernel.

## 4. Source tree map

### 4.1 `semshell/kernel/`

This package is the trusted semantic execution core.

- `process.py` defines ProcessState, ownership/wait/cancel modes, ProcessError,
  ProcessContext, immutable terminal ProcessResult, and read-only
  ProcessSnapshot. These are the public lifecycle values.
- `actions.py` owns the values returned by guest programs: Send, Spawn, Cancel,
  Detach, Wait, Yield, DiscoverImages, InvokeResource, Exit, and Fail.
  `ProcessAction` is their closed union. These types do not inherit from or
  alias Host Control operations.
- `events.py` defines mailbox values: Started, MessageReceived,
  ChildrenCompleted, operation continuations, ConsoleInput, catalog discovery,
  and resource completion/rejection. It also defines Message and MessageKind.
- `operations.py` defines the temporary typed Host Control payloads.
  `KernelOperation` includes trusted operations; the narrower
  `ExternalControlOperation` deliberately excludes RegisterImage, SendMessage,
  and DetachProcess where external identity is insufficient.
- `errors.py` contains stable Kernel exception categories used internally and
  normalized by ControlGateway.
- `_runtime.py` contains the mutable ProcessControlBlock and ResourceTaskRecord,
  plus the immutable TerminalDecision and Kernel-owned cleanup task references.
  They are Kernel-owned implementation state and must never be exposed to guest
  programs, Control adapters, or CLI rendering.
- `kernel.py` implements ProcessKernel.
- `__init__.py` is the guest/kernel convenience export surface. Control code
  imports its distinct payloads directly from `kernel.operations`.

The trusted-only exclusions have different reasons: RegisterImage carries an
executable factory and belongs to Host bootstrap; SendMessage requires an
authentic running source PID; DetachProcess requires the ownership context of a
running parent Process.

The important public ProcessKernel methods are:

- `start()` and `stop()` manage the Kernel lifetime;
- `register_image()`, `unregister_image()`, `list_images()`, and
  `resolve_image()` expose Catalog operations through a Kernel boundary;
- `spawn()` and `spawn_many()` admit root or child Processes;
- `send()` is trusted PID-attributed IPC, while `deliver_console_input()` is a
  distinct Host-device path;
- `wait()`, `cancel()`, and `reap()` manage or observe lifecycle;
- `inspect()`, `list_processes()`, and `tree()` return immutable snapshots;
- `authority_decisions()` and `resource_audit_events()` return audit evidence;
- `list_resource_bindings()` returns factory-free Host diagnostics.

The main private paths in `kernel.py` are grouped by responsibility:

- `_admit_many()` and `_effective_authority()` perform atomic admission;
- `_schedule()` and `_activate()` enforce one activation per Process;
- `_apply_action()` is the generic Action dispatch point;
- `_apply_resource()`, `_run_resource()`, and `_settle_resource()` implement the
  authenticated resource lifecycle without filesystem-specific branches;
- `_apply_spawn()`, `_apply_wait()`, `_apply_cancel()`, and `_apply_detach()`
  implement structured process operations;
- `_commit_decision()` freezes the unique terminal decision;
- `_finalize()` owns cancellation and abnormal cleanup outside activation slots,
  and `_publish_result()` publishes the sole ProcessResult;
- `_shutdown()` owns shared shutdown using stable Process references;
- `_snapshot()` is the only ProcessControlBlock-to-public-view conversion.

### 4.2 `semshell/software/`

This package describes installable semantic software independently of running
Processes.

- `program.py` defines the minimal ProcessProgram protocol: asynchronous
  `handle()` plus bounded-cleanup `stop()`.
- `image.py` defines CapabilitySpec, immutable ProcessImage,
  factory-free ProcessImageDescriptor, and ProcessSpec. A factory belongs to
  trusted Host registration and never appears in guest discovery.
- `catalog.py` implements exact image lookup, versioned registration,
  capability provider indexes, deterministic listing, ambiguity rejection, and
  exact provider resolution.
- `__init__.py` intentionally avoids convenience imports that would create
  Action/software dependency cycles.

### 4.3 `semshell/security/`

This package implements semantic identity and admission authority.

- `principal.py` defines namespaced Principal identity.
- `authority.py` defines exact Permission `(capability, scope)` values and the
  immutable Authority set with subset, intersection, union, difference, and
  reduction operations.
- `policy.py` defines AdmissionRequest, AdmissionResult, approval values, the
  Policy protocol, and DefaultPolicy. Policy evaluates requested authority
  against the caller ceiling, image ceiling, minimum requirements, ACL, and
  configured approval evidence.
- `audit.py` defines immutable AuthorityDecisionRecord entries.
- `__init__.py` exports the public security API.

Authority is semantic mediation, not Python code containment. In-process guest
code can still import Host modules directly.

### 4.4 `semshell/resources/`

This package defines the generic guest-to-Host resource boundary.

- `types.py` defines opaque ResourceBindingId and ResourceInvocationId,
  factory-free binding descriptors, authenticated ResourceInvocation,
  ResourceErrorCode, ResourceAuditEvent, and recursive immutable input
  freezing.
- `bridge.py` defines the passive HostResourceBridge protocol and
  ResourceBridgeError with fixed public messages.
- `registry.py` binds trusted descriptors to bridges in a startup-fixed,
  immutable ResourceRegistry.
- `path.py` validates the portable relative-path grammar used by `read_text`.
- `memory.py` implements deterministic InMemoryResourceBridge for conformance
  and cancellation tests.
- `local.py` implements bounded UTF-8 reads under one resolved local root. It
  performs no writes and assumes a trusted tree without adversarial concurrent
  symlink or junction mutation.
- `__init__.py` exports the public resource API.

The guest Action contains only binding ID, operation, and input. Process PID,
Principal, Authority, and invocation ID are derived by the Kernel.

### 4.5 `semshell/control/`

This package is the transport-neutral Host administration protocol.

- `request.py` defines protocol version, session-local RequestId, and
  ControlRequest. Construction accepts only ExternalControlOperation values.
- `reply.py` defines ReplyStatus and the unique terminal ControlReply envelope.
- `error.py` defines stable ControlError layers and SessionProtocolError for
  failures outside an admitted request lifecycle.
- `session.py` contains ControlContext, session/request state enums,
  RequestHandle's exactly-once reply gate, and ControlSession admission,
  capacity, interruption, and close behavior.
- `gateway.py` implements ControlGateway. `submit()` admits and dispatches;
  `interrupt()` stops request observation without implying Process rollback;
  `close_session()` closes transport state without cancelling Processes. The
  private `_execute()` maps typed operations only to public ProcessKernel APIs,
  and `_normalize_error()` produces stable ControlErrors.
- `audit.py` defines terminal and late Control audit outcomes.
- `__init__.py` exports the protocol surface.

Control interruption and Process cancellation are intentionally different.
For example, interrupting WaitProcess stops one external observer; it does not
cancel the target Process or its completion future.

### 4.6 `semshell/cli/`

This package adapts a local terminal to the Control protocol.

- `commands.py` uses strict shell tokenization and validation to convert one
  input line into a typed ExternalControlOperation or local `help`/`quit`.
  Parser failures occur before RequestId allocation. External `send` is
  intentionally unavailable.
- `rendering.py` recursively encodes public dataclasses, mappings, enums,
  Authorities, timestamps, and collections into deterministic JSON-compatible
  values. Unknown Host objects and non-finite numbers fail closed.
- `control.py` owns the session-lived sequential REPL. LocalControlCLI allocates
  request IDs, submits through ControlGateway, renders one terminal result per
  command, handles interruption, and closes the session and Kernel.
- `main.py` selects either the original Operator architecture demo or the local
  Control CLI. `_run()` converts DemoReport into its older human-readable JSON
  shape; `main()` owns process exit codes.
- `__init__.py` marks the package boundary without widening the public API.

### 4.7 `semshell/host/`

- `console.py` defines ConsoleBridge, which is fixed to one admitted Process PID
  and delivers principal-attributed ConsoleInput. It is not generic IPC and
  cannot claim an arbitrary source PID.
- `__init__.py` exports Host adapters.

The current console path is input-only. Long-lived output, subscriptions, and
backpressure are deferred.

Trusted bootstrap code decides which Principal may construct a ConsoleBridge
and which PID it binds. Version 0.3 has no external console-binding operation or
remote authorization protocol.

### 4.8 `semshell/shells/`

This package contains replaceable Operator ProcessPrograms.

- `base.py` defines OperatorTask and shared spawn/completion helpers.
- `human.py` implements HumanShell from structured startup or ConsoleInput.
- `rule.py` implements deterministic RuleShell selection.
- `llm.py` implements LLMShell using a provider-neutral SemanticBackend.
- `codec.py` converts structured model/backend data into the same ProcessAction
  values used by other Operators; it is not a Kernel codec.
- `__init__.py` exports the Operator software API.

All three shells discover factory-free image metadata and request ordinary
Spawn Actions. None receives direct Kernel access.

### 4.9 `semshell/llm/`

This package isolates model-provider concerns from the runtime.

- `base.py` defines LLMRequest, LLMResponse, TokenUsage, and the asynchronous
  SemanticBackend protocol.
- `scripted.py` implements a deterministic offline backend for tests and demos.
- `openai.py` implements OpenAIResponsesBackend and normalizes SDK output into
  provider-neutral values.
- `__init__.py` exports the model adapter API.

No OpenAI or other provider SDK type enters the Kernel, Actions, Events, or
Process state.

### 4.10 `semshell/examples/`

- `architecture_demo.py` defines the echo worker, fan-out/fan-in coordinator,
  replaceable Operator factories, demo Catalog, and `run_demo()` report.
- `resource_demo.py` defines WorkspaceReaderProgram and `run_resource_demo()`;
  the unchanged guest runs against both fake and local bridges.
- `control_runtime.py` builds the deterministic Catalog, Kernel,
  ControlGateway, and local ControlSession used by version 0.3.
- `__init__.py` exports executable proof helpers.

Examples are architecture proofs and trusted bootstrap assembly, not special
Kernel applications.

### 4.11 Package root

- `semshell/__init__.py` declares the package version and top-level convenience
  API.
- `requirements.txt` is the single dependency list for runtime adapters and
  development validation. The project intentionally does not require a
  `pyproject.toml` at this prototype stage.

### 4.12 Documentation

- `docs/design.md` presents the short architecture argument.
- `docs/semantics.md` is the normative public behavioral summary.
- `docs/security-model.md` states trust boundaries and non-claims.
- `docs/codebase-guide.md` is this descriptive source map.
- `docs/reference-and-production.md` separates this executable design from the
  intended Linux/OCI application architecture.
- `devdoc/` contains detailed milestone semantics, drafts, and planning
  material rather than the concise public contract.

When this guide and `semantics.md` differ, `semantics.md` is authoritative. This
guide describes the source tree through version 0.3 and should be updated when
files or boundaries move.

## 5. Four important execution paths

### 5.1 Guest Process activation

```text
Kernel scheduler
  -> pop one ProcessEvent
  -> ProcessProgram.handle(context, event)
  -> receive one ProcessAction
  -> validate and commit its effect
  -> enqueue a continuation Event or publish ProcessResult
```

The same Process is never activated concurrently. READY means a deliverable
Event exists; WAITING means an explicit wait, resource invocation, or empty
mailbox prevents progress.

### 5.2 Spawn and authority

```text
guest Spawn / Host Control SpawnProcesses
  -> Catalog exact or capability resolution
  -> execute ACL and Policy evaluation
  -> AuthorityDecisionRecord
  -> factory creates ProcessProgram
  -> Kernel assigns monotonic PID
  -> Started Event enters the mailbox
```

A ProcessSpec requests Authority but cannot grant it. Child authority is
bounded by its caller unless trusted policy accepts configured approval.
The two entry payloads are independent types; each boundary calls the trusted
Kernel admission API with its own authenticated identity.

### 5.3 Resource invocation

```text
InvokeResource
  -> Kernel allocates invocation ID
  -> exact binding and operation lookup
  -> exact Permission check
  -> immutable authenticated ResourceInvocation
  -> HostResourceBridge.invoke()
  -> ResourceCompleted or ResourceRejected
```

Only one resource invocation may be pending per Process. Cancellation clears
the continuation and suppresses late bridge results; bridge capacity is held
until the actual task settles.

### 5.4 Local Control command

```text
terminal line
  -> parse_command()
  -> typed ExternalControlOperation
  -> ControlRequest(RequestId)
  -> ControlGateway.submit()
  -> public ProcessKernel method
  -> exactly one ControlReply
  -> deterministic JSON rendering
```

Parser errors consume no RequestId. Request interruption does not roll back an
already committed Kernel effect. The CLI cannot use SendMessage because a
ControlSession has no authentic source PID.

Handler exceptions are normalized into a failed ProcessResult, and cancellation
uses bounded `stop()` cleanup. Control interruption races through the
RequestHandle reply gate; an already dispatched mutation may complete later and
is audited without changing the earlier INTERRUPTED reply.

## 6. Tests as executable architecture evidence

- `test_kernel.py` covers scheduling, lifecycle, IPC, ownership, waiting,
  cancellation, and inspection.
- `test_kernel_lifecycle.py` covers shutdown races, deep trees, terminal
  competition, cleanup ownership, and finalizer fault supervision.
- `test_public_types.py` covers public value construction and shared operation
  types.
- `test_catalog.py` covers registration, resolution, ambiguity, and in-use
  unload behavior.
- `test_authority_policy.py` covers exact authority reduction, denial, approval,
  ACL, and audit.
- `test_control_protocol.py` covers session/request state and the exactly-once
  reply gate.
- `test_control_gateway.py` covers Kernel dispatch, capacity, interruption,
  late mutation, authority ceiling, and observation parity.
- `test_resource_values.py` covers immutable input, registry behavior, path
  grammar, and fake/local bridge equivalence.
- `test_kernel_resources.py` covers authenticated invocation, denial before
  Host execution, capacity, cancellation, and late-result suppression.
- `test_openai_backend.py` covers provider-output normalization with injected
  fake clients and no network.
- `test_operator_demo.py` proves HumanShell, RuleShell, and LLMShell share one
  architecture and produce equivalent task topology/results.
- `test_cli_control.py` covers strict parsing, safe rendering, within-session
  runtime behavior, audit correlation, interruption, shutdown, and mandatory
  Gateway routing.

## 7. Boundary placement rules

Use these rules to understand the existing reference packages and to keep any
maintenance change inside the frozen design scope:

- a new generic lifecycle primitive belongs in `kernel/` only if every kind of
  Process needs it;
- a new executable or orchestration strategy normally belongs in `software/`,
  `shells/`, or another guest package as a ProcessProgram;
- reference access to files, networks, secrets, databases, subprocesses, or
  models is represented as a scoped `resources/` bridge when it crosses the
  Host boundary;
- Host administration belongs in typed `control/` operations;
- the existing terminal-only proof remains in `semshell/cli/`; production JSON
  Lines, socket, HTTP, FUSE, and frontend adapters belong in the separate
  runtime repository and must preserve the language-neutral Control contract;
- provider-specific model code belongs in `llm/` and must normalize into
  provider-neutral values before reaching guest software;
- production containment and execution belong in a separate Linux/OCI runtime
  repository, not in a future Python Kernel package and not in semantic
  Authority claims;

The practical test is simple: adding a new tool, LLM provider, coordinator, or
Operator should not require a role-specific branch in ProcessKernel.

## 8. Current boundaries and deferred work

The implemented runtime is single-process, asyncio-driven, in-memory, and
non-durable. Current Host filesystem mediation is read-only and soft because
trusted in-process Python can bypass it.

Not yet implemented:

- remote JSON Lines, socket, HTTP, or FUSE adapters;
- long-lived output streams, subscriptions, and backpressure;
- persistence, replay, checkpoint, or resume;
- subprocess, container, WASM, or worker isolation;
- writable filesystem transactions or network bridges;
- supervisors, restart policy, resource accounting, or multi-worker leases;
- a package manager or remote Catalog;
- production authentication and durable session identity.

These limitations are intentional. The current repository proves the flattened
Process model, explicit Host bridges, and boundary-compatible local Control
without claiming a complete operating system.

## 9. Running and validating the repository

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm

.\.venv\Scripts\python.exe -m semshell.cli.main control

.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
```
