# SemShell 0.3 Interactive Control CLI Plan

## 1. Purpose

Version 0.3 proves that the transport-neutral Control protocol is usable from
a persistent local command-line adapter without turning an external terminal
into a SemShell Process.

The proof is about boundary discipline and runtime operability:

1. one CLI process keeps a Kernel, ControlGateway, and ControlSession alive;
2. every administration command becomes a typed ControlRequest;
3. every admitted command produces exactly one terminal ControlReply;
4. the CLI reads only public reply values and never accesses Kernel internals;
5. guest execution continues to use Event/Action semantics.

This is a local administration REPL, not the final HumanShell user experience.

## 2. Why 0.3 is not yet a long-lived Operator shell

The current `ConsoleBridge` delivers principal-attributed input to one bound
Process, but there is no matching console-output or stream protocol. The
current `HumanShell` also completes after one `OperatorTask`.

Making it a persistent interactive shell now would require decisions about:

- output ownership and routing;
- zero-or-more outputs versus one terminal request result;
- bounded buffering and slow consumers;
- disconnect and reconnection;
- whether a shell survives a terminal frontend;
- concurrent tasks and prompt readiness.

Those belong to the later provider-neutral stream/frontend milestone. Version
0.3 must not introduce an unbounded callback or inspect Process mailboxes as a
shortcut.

## 3. Boundary model

```text
Local terminal
    -> CLI parser and renderer
    -> one local ControlSession
    -> ControlRequest / ControlReply
    -> ControlGateway
    -> public ProcessKernel operations

Guest Process
    -> ProcessAction
    -> ProcessKernel
    -> ProcessEvent
```

The two paths may request related effects, but they have different identity,
lifecycle, and continuation semantics. A ControlSession has a Principal and an
Authority ceiling, but has no PID, owner, mailbox, or Process lifecycle.

## 4. Closed decisions

### 4.1 Runtime lifetime

`semshell control` starts one in-memory runtime and enters a sequential REPL.
The Kernel and Process Table remain live until `quit`, end-of-input, or
`KeyboardInterrupt`. A command invocation is not a new Kernel.

The CLI owns orderly shutdown:

1. stop accepting input;
2. close the ControlSession;
3. stop the Kernel using its existing lifecycle semantics;
4. return a defined process exit code.

`quit` and end-of-input return exit code `0`. `KeyboardInterrupt` performs the
same orderly shutdown and returns `130`. Startup or shutdown failure returns
`1`. Kernel stop uses the existing bounded cancellation cleanup: it cancels and
awaits live root Processes but does not reap their terminal records. The CLI
adds no second shutdown timeout or escalation mechanism in 0.3.

Terminal input is read outside the asyncio event-loop thread, so Process
scheduling and resource completion continue while the prompt is idle.
`KeyboardInterrupt` while reading input begins shutdown immediately. While a
parsed request is being submitted or its reply is awaited, submission is
shielded long enough to obtain its RequestHandle; the adapter then calls
`ControlGateway.interrupt` for that RequestId, awaits and renders the resulting
`INTERRUPTED` reply, closes the session, stops the Kernel, and exits `130`.
Interrupting request observation never cancels or rolls back a Process effect.

### 4.2 CLI identity and authority

Bootstrap code establishes the local session Principal and Authority before
opening the session. Command text cannot claim a Principal or expand the
session Authority. The local proof grants only `control.process.cancel`,
`control.process.reap`, and `control.catalog.unregister` administration
permissions. Requested Process authority in `spawn` remains bounded by the
session Authority and image policy.

The first proof may use a deterministic built-in demo Catalog and explicit
bootstrap Authority configuration. Image installation and arbitrary Python
factory loading are not CLI operations.

### 4.3 Sequential adapter policy

The interactive adapter submits one request and renders its terminal reply
before reading the next command. This makes terminal behavior deterministic
without weakening the concurrent Control protocol.

`wait` may therefore block the REPL until completion or timeout. Parallel jobs,
background waits, request interruption from another prompt, and asynchronous
notifications are deferred.

### 4.4 Request identity

The adapter allocates opaque monotonic request names within its session, for
example `cli-1`, `cli-2`, and `cli-3`. Users do not supply RequestIds. IDs remain
visible in structured output and Control audit.

Parsing success is the allocation boundary. A successfully parsed gateway
command consumes one RequestId and is submitted to the session. Session
admission then creates the exactly-once reply obligation. Kernel, policy, busy,
timeout, and argument failures after admission are terminal rejected replies
and receive Control audit records. A parser rejection occurs before RequestId
allocation and admission, so it has neither a ControlReply nor an audit record.

Failure of the locally constructed session itself to admit a parsed request is
an adapter/runtime invariant failure. The adapter emits a safe internal error,
performs orderly shutdown, and exits `1`.

### 4.5 External Send remains unavailable

`send` is not a version 0.3 Control command. An external session cannot provide
an authentic Process source PID, and using a synthetic PID would collapse the
Host/guest boundary.

Process-to-Process messages continue to originate only from a running
Process's `Send` Action. Human input to a shell uses a `ConsoleBridge` bound to
that shell PID. A future external-ingress resource may define a different,
explicit provenance model; it must not be named ordinary Process IPC.

### 4.6 No direct Kernel fallback

The CLI adapter may bootstrap and stop the runtime as trusted Host code. For
all commands after startup it must use ControlGateway only. It must not call
`kernel.list_processes`, `kernel.spawn`, or other operation methods directly,
and it must never read a ProcessControlBlock, mailbox, task, or bridge object.

## 5. Minimal command surface

| CLI command | Typed Control operation | Result |
| --- | --- | --- |
| `images` | `ListImages` | deterministic image descriptors |
| `ps` | new `ListProcesses` | deterministic Process snapshots |
| `inspect PID` | `InspectProcess` | one Process snapshot |
| `tree PID` | `InspectTree` | ordered subtree snapshots |
| `spawn ...` | `SpawnProcesses` | admitted root PIDs |
| `wait PID [--timeout S]` | `WaitProcess` | immutable ProcessResult |
| `cancel PID [--tree] [--reason TEXT]` | `CancelProcess` | terminal ProcessResult |
| `reap PID` | `ReapProcess` | removed ProcessResult |
| `help` | adapter-local | command usage; no request |
| `quit` | adapter-local | orderly session/runtime shutdown |

`ListProcesses` is the only new Control operation required for 0.3. It returns
the same deterministic immutable snapshots as the public Kernel inspection
API. It is observational and does not consume mutation capacity.

`resolve` and `unregister-image` remain available in the protocol but are not
required in the first REPL proof. `send`, console attachment, image
registration, resource binding mutation, and Kernel restart are absent.

## 6. Command input contract

The parser produces typed operation values, not generic command dictionaries.
The initial `spawn` syntax should remain deliberately narrow:

```text
spawn --image IMAGE@VERSION [--input JSON]
spawn --capability NAME [--provider IMAGE@VERSION] [--input JSON]
      [--authority CAPABILITY[=SCOPE]]...
```

Rules:

- exactly one of image or capability is required;
- provider is valid only with capability;
- input is one JSON value and defaults to `null`;
- each authority flag creates one exact Permission;
- malformed syntax is rejected locally before RequestId allocation;
- a valid command receives a RequestId even if the gateway rejects it;
- command parsing never imports or constructs ProcessImage factories.

Image reference, capability, and provider tokens must be non-empty; Catalog and
typed value validation remain authoritative for semantic validity. An authority
token splits on its first `=`. Capability is non-empty, scope is a non-empty
literal string when `=` is present, and absence of `=` means scope `None`.
Repeated identical permissions collapse through Authority set semantics.

The remaining commands accept decimal positive PIDs. Timeout is floating-point
seconds and must be finite and non-negative. Timeout produces the existing
rejected `gateway.timeout` ControlError with `retryable=true` and never cancels
or mutates the observed Process. Cancellation reason defaults to `cancelled
from local control`.

`CancelProcess` keeps its existing contract: success waits for and returns the
target's terminal ProcessResult. Cancelling an already terminal Process is
idempotent; missing or reaped targets use the existing
`kernel.process_not_found` rejection.

## 7. Output contract

The adapter renders every terminal ControlReply as one JSON-compatible object:

```json
{
  "request_id": "cli-4",
  "operation": "InspectProcess",
  "status": "SUCCEEDED",
  "value": {},
  "error": null
}
```

A single recursive encoder owns conversion of an explicit closed set of
SemShell public dataclasses and enums,
Mapping values, tuples, sets, Principal, Authority, Permission, and timestamps.
It must reject unsupported Host objects rather than use `repr()` or
`default=str`, because those fallbacks can leak factories, bridges, paths, or
unstable implementation details.

Output ordering is deterministic:

- dataclasses use declared public field order;
- mappings require string keys and use lexicographic key order;
- Permission values sort by `(capability, scope is not None, scope or "")`;
- other sets sort by the canonical compact JSON encoding of each encoded item;
- Process and image collections retain Kernel/Catalog deterministic order;
- aware timestamps convert to UTC with six fractional digits and a `Z` suffix;
  naive timestamps are rejected;
- `StrEnum` values use their string value and other Enum values recursively
  encode `.value`.

Canonical compact JSON means UTF-8 data produced with ASCII escaping enabled,
lexicographically sorted object keys, separators `,` and `:` with no optional
whitespace, and non-finite numbers rejected. The value encoder rejects NaN and
positive or negative infinity before either output or set sorting.

Every reply envelope contains `request_id`, `operation`, `status`, `value`,
`error`, and `metadata`. `value` is null on failure; `error` is null on success.
The operation is the ControlReply operation name and status is the ReplyStatus
string. Error objects contain `code`, `message`, `origin`, `retryable`, and
`details`.

The local CLI writes one compact JSON object followed by a newline to stdout
for each command outcome. An interactive prompt is written to stderr, keeping
scripted stdout unambiguous. This local framing does not define connection,
correlation, or backpressure semantics for the deferred JSON Lines transport.

Unsupported values fail closed. The adapter emits a safe envelope with the
original request identity and `cli.encoding_failed`, records no Host object or
raw exception, then continues. The underlying ControlReply and audit commit
remain authoritative even when their value cannot be displayed.

The encoding-failure envelope is a display-layer substitution, not a second
ControlReply:

```json
{
  "request_id": "cli-4",
  "operation": "InspectProcess",
  "status": "ENCODING_FAILED",
  "value": null,
  "error": {
    "code": "cli.encoding_failed",
    "message": "control reply value could not be encoded",
    "origin": "adapter",
    "retryable": false,
    "details": {}
  },
  "metadata": {}
}
```

`ENCODING_FAILED` is not a ReplyStatus and does not alter the already committed
reply or audit outcome. The normal six-field and exact-ControlError rules apply
only when encoding succeeds.

## 8. Error and exit behavior

There are two error layers:

1. parser errors occur before admission and render
   `{"adapter_error":{"code": CODE,"message": MESSAGE}}` with no RequestId or
   Control audit record;
2. admitted request failures render the exact ControlError from the unique
   ControlReply.

Parser codes are closed initially to `cli.unknown_command`,
`cli.invalid_syntax`, `cli.invalid_json`, and `cli.invalid_value`. Messages are
fixed by the parser and never include exception text. Parser and admitted
request errors are written to stdout using the same one-object-per-line rule.

One rejected command does not terminate the REPL. Exit codes follow section
4.1.

Python exception types, tracebacks, ProcessProgram objects, Host paths, and raw
unexpected exception text must not enter normal CLI output.

## 9. Proposed package structure

```text
semshell/
├── cli/
│   ├── main.py          # top-level argument selection only
│   ├── control.py       # persistent local REPL lifecycle
│   ├── commands.py      # text -> typed operation
│   └── rendering.py     # public values -> JSON-compatible values
├── control/
│   └── ...              # unchanged transport-neutral protocol/gateway
└── examples/
    └── control_runtime.py  # deterministic proof Catalog/bootstrap assembly
```

The exact bootstrap filename may change, but construction of demo software must
not be mixed into parsing or rendering.

## 10. Implementation phases

### Phase 0: close adapter semantics

- Freeze the administration-versus-Operator distinction.
- Freeze sequential REPL, request allocation, shutdown, parser-error, and output
  behavior.
- Amend the old TODO wording so it no longer promises external `send`.

### Phase 1: observation parity

- Add `ListProcesses` to KernelOperation and ExternalControlOperation.
- Dispatch it through ControlGateway using only the public Kernel snapshot API.
- Add protocol and gateway conformance tests.

### Phase 2: reusable CLI values

- Implement strict command parsing into existing typed operations.
- Implement the shared JSON-compatible public-value encoder.
- Add table-driven parsing, deterministic rendering, and leakage tests.

### Phase 3: persistent local adapter

- Build the deterministic runtime assembly.
- Implement the sequential request/reply loop and orderly shutdown.
- Keep the existing `demo --operator ...` behavior compatible.
- Add scripted-input integration tests instead of terminal automation.

The proof Catalog includes `demo.echo@1`, whose Started activation exits with
its JSON input unchanged. This freezes the terminating program used by the
multi-command transcript without expanding the CLI into an image loader.

### Phase 4: architecture proof and docs

- Prove `spawn -> ps/inspect -> wait -> reap` in one live CLI runtime.
- Prove denied authority returns a ControlReply and the REPL remains usable.
- Prove every admitted command has matching Control audit identity.
- Update README, public semantics, design, and security documentation.

## 11. Required invariants

1. The CLI is an adapter, not a Kernel protocol and not a Process.
2. A CLI ControlSession cannot originate Process IPC.
3. All post-bootstrap administration commands traverse ControlGateway.
4. Every successfully admitted command produces one terminal reply; failure of
   the local session to admit a parsed command is a fatal runtime invariant
   failure outside the normal command protocol.
5. Parser rejection produces neither RequestId consumption nor Kernel effects.
6. CLI session Authority cannot be expanded by command input.
7. Request interruption or terminal disconnect does not imply Process rollback.
8. Rendering cannot expose executable factories or arbitrary Host objects.
9. Guest software remains role-neutral and unchanged.
10. 0.3 introduces no stream, remote transport, persistence, or containment
    claim.

## 12. Test matrix

### Protocol and gateway

- `ListProcesses` is accepted externally and returns deterministic snapshots.
- empty and populated Process Tables are represented without internal objects.
- observation does not consume the mutation semaphore.
- existing prohibition of external Send remains executable.

### Parser

- every required command maps to the exact typed operation;
- invalid PID, timeout, JSON, image/capability combination, and authority syntax
  fail before request allocation;
- quoted cancellation reasons and JSON containing spaces are preserved;
- `help` and `quit` never reach the gateway.

### Renderer

- replies, errors, descriptors, snapshots, results, authority, and timestamps
  encode deterministically;
- unsupported objects fail closed;
- no factory, bridge, traceback, or raw exception appears.

### End to end

- multiple commands observe one persistent Process Table;
- a root Process can be spawned, inspected, waited, and reaped;
- rejection does not end the session;
- end-of-input and `quit` close the session and Kernel;
- each admitted request has one matching terminal reply and audit record.
- the normative transcript spawns `demo.echo@1` with `{"value":"ok"}`, observes
  the same PID through `ps` and `inspect`, waits for that exact result, reaps it,
  and then receives `kernel.process_not_found` when inspecting it;
- gateway spies confirm every parsed administration command traverses
  `ControlGateway.submit`, while a source check prohibits operational
  ProcessKernel calls from CLI command handlers;
- external Send remains rejected by ControlRequest construction.

## 13. Completion criteria

Version 0.3 is complete when:

1. `semshell control` provides the required persistent local command set;
2. the CLI contains no direct post-bootstrap Kernel operation call;
3. `ListProcesses` completes observation parity through ControlGateway;
4. scripted integration tests prove one live multi-command session;
5. external Send remains structurally impossible;
6. output is deterministic, JSON-compatible, and free of Host implementation
   objects;
7. all tests remain offline and deterministic;
8. public documentation accurately distinguishes Control CLI, ConsoleBridge,
   and Operator Processes.
9. parser/renderer tests cover every required command and adapter error code,
   and shutdown tests assert exit codes `0`, `1`, and `130`.

## 14. Deferred after 0.3

- JSON Lines and socket transports;
- concurrent/background CLI requests;
- request lookup or uncertain-outcome recovery across sessions;
- persistent runtime daemon attachment;
- long-lived HumanShell output and frontend subscriptions;
- provider/model streaming and backpressure;
- external ingress resources;
- FUSE namespace adapters;
- Docker and isolated Process executors.
