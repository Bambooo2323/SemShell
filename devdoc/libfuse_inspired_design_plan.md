# Libfuse-Inspired Interface Plan

> Historical design context. Current guarantees are defined in
> [docs/semantics.md](../docs/semantics.md), with final evidence in the
> [design-edition validation record](../docs/design-edition-validation.md).
> The pre-removal Stage 3 implementation is recoverable from Git tag
> `complete-reference-20260915`; older contracts remain in ancestor history.
> Proposals and completion criteria below do not add active API guarantees.

## 1. Purpose

This plan uses libfuse as an architectural reference for exposing SemShell through
an OS-shaped, request/reply interface. It does not turn the SemShell kernel into a
filesystem and does not add a real filesystem to the 0.1 scope.

The useful libfuse idea is the separation between:

1. a stable protocol boundary owned by a kernel-facing component;
2. a user-space implementation that handles typed requests;
3. a session that owns transport, negotiation, concurrency, and shutdown; and
4. optional high-level adapters that trade control for convenience.

SemShell should apply the same separation to process control. The process table
remains the authoritative state. A filesystem-shaped namespace is only one view
and control adapter over the public Kernel API.

## 2. Architectural conclusion

```text
CLI / LLM / script / future FUSE client
                  |
          Control Adapter
                  |
       ControlSession protocol
                  |
       typed Request / Reply
                  |
          SemShell Gateway
                  |
       public ProcessKernel API
                  |
       authoritative process state
```

The adapter must never read or mutate `ProcessControlBlock` directly. It may only
use stable public operations such as catalog listing, spawn, send, wait, cancel,
inspect, tree, and reap.

The same request protocol should support an in-memory adapter first, JSON Lines
and CLI adapters next, and a real FUSE adapter only after the protocol is stable.
Running ProcessPrograms continue to use Event/Action semantics; an external
session is not wrapped in a fake Process merely to reuse the protocol envelope.

## 3. Mapping from libfuse to SemShell

| libfuse concept | SemShell counterpart | Design consequence |
| --- | --- | --- |
| FUSE session | `ControlSession` | Own connection identity, negotiated features, in-flight requests, and shutdown. |
| `fuse_req_t` | `RequestHandle` | Give every operation a unique identity and exactly one terminal reply. |
| low-level operation table | typed `ControlRequest` handlers | Preserve explicit operations instead of hiding behavior behind role-specific objects. |
| `fuse_reply_*` | `ControlReply` | Return success or structured failure through one protocol path. |
| session loop | transport pump | Keep transport scheduling outside the Process Kernel. |
| interrupt callback/state | request cancellation state | Make cancellation observable even if it arrives before a handler registers interest. |
| inode / file handle | stable namespace node / open view handle | Separate lookup identity from a live access instance. Do not equate either with PID. |
| lookup count and `forget` | adapter reference accounting | Release adapter-side cached nodes without reaping processes or changing Kernel ownership. |
| mount/unmount | attach/detach adapter session | Adapter lifecycle must not imply Kernel lifecycle. |
| high-level API | convenience path/command adapter | Build only after low-level typed semantics are defined. |

## 4. Semantic decisions to close before implementation

### 4.1 Request identity and reply discipline

- `RequestId` is unique within one live `ControlSession`.
- A request receives exactly one terminal `ControlReply`.
- Duplicate replies are protocol errors and are never forwarded to the client.
- A reply contains the request ID, operation name, status, optional value, and a
  structured error.
- Transport failure does not roll back a Kernel operation that already committed.
- Operations that may outlive a connection must expose their committed identity,
  such as the spawned PID, through audit state or idempotency support later.

### 4.2 Sessions are not processes

- A `ControlSession` is transport state, not a SemShell Process.
- A shell or gateway may itself run as a Process, but the protocol does not require
  every client connection to consume a PID.
- Closing a session cancels its in-flight observation requests by default, but it
  does not automatically cancel processes spawned through the session.
- Spawn ownership continues to be expressed by `ProcessSpec.ownership` and parent
  PID, never by connection lifetime.

### 4.3 Request interruption versus process cancellation

- Interrupting `wait` stops waiting for the reply; it does not cancel the target.
- Interrupting `spawn` after admission does not cancel the admitted process.
- `cancel_process` is a separate, explicit mutating request.
- Each request handle stores interruption state so an early interrupt cannot be
  lost before a handler begins waiting.
- Cancellation races must resolve to one reply using the same winner rules as the
  Kernel lifecycle semantics.

### 4.4 Namespace identity

- Namespace node IDs are adapter-local and must not be PIDs disguised as inodes.
- PID reuse is already forbidden within one live Kernel, but namespace identity
  still needs a node kind and generation/session boundary.
- Lookup/reference release only invalidates adapter caches; it never calls
  `reap()` implicitly.
- Open handles represent a stable view or command transaction. They must remain
  valid or fail explicitly if the underlying process is reaped.

### 4.5 Consistency and caching

- The Process Kernel remains the single source of truth.
- Initial namespace reads use snapshot-at-operation semantics.
- Directory listings may be internally consistent snapshots rather than live
  iterators over a mutating process table.
- The first version declares metadata non-cacheable or short-lived. Notification
  and invalidation support is deferred until measurements show it is necessary.
- Writes must never rely on a later read to discover whether an operation worked;
  every mutation returns a structured result.

### 4.6 Authority and caller context

- Every session is bound to a `Principal` and maximum delegated `Authority` during
  admission.
- Each request carries an immutable caller context derived from that session.
- Path visibility is not authorization. All mutations still pass through Kernel
  policy and authority checks.
- A future `allow_other`-like option must be an explicit gateway policy, not a
  mount convenience flag that silently widens authority.

## 5. Proposed virtual namespace

The first namespace model should be read-mostly and mechanically derived from
public snapshots:

```text
/
|-- images/
|   `-- <escaped-image-reference>/
|       |-- manifest.json
|       `-- capabilities.json
|-- capabilities/
|   `-- <escaped-capability>/providers.json
|-- processes/
|   `-- <pid>/
|       |-- status.json
|       |-- context.json
|       |-- children.json
|       `-- result.json
`-- sessions/
    `-- <session-id>/info.json
```

Control should not begin with magic writes to status files. The first mutation
surface should use explicit typed requests in the gateway. If a FUSE view later
needs writable control nodes, use transaction-like endpoints such as
`/sessions/<id>/requests/<request-id>` with one JSON request and one terminal JSON
reply. Do not make `echo 1 > cancel` the canonical protocol.

## 6. Implementation milestones

### Milestone A: Freeze the control protocol

- Define `RequestId`, `SessionId`, `ControlContext`, and `RequestHandle`.
- Define typed requests for factory-free `list_images`, `resolve`, safe
  `unregister_image`, root `spawn`, `wait`, `cancel`, `inspect`, `tree`, and
  `reap`. Executable factory registration remains a trusted host boundary.
  External message ingress remains unavailable until it can be represented
  without forging a source PID.
- Define one `ControlReply` envelope and map Kernel errors without leaking Python
  exceptions or transport-specific error numbers.
- Specify exactly-once reply, interrupt, disconnect, and late-completion behavior.
- Add protocol conformance tables before runtime code.

Completion criterion: the protocol can be implemented without knowing whether the
transport is CLI, JSON Lines, a socket, or FUSE.

### Milestone B: Build an in-memory gateway

- Implement `ControlGateway` only against public `ProcessKernel` methods.
- Implement `ControlSession` with bounded in-flight requests and explicit close.
- Add request admission, structured audit events, and caller-context propagation.
- Use fake transports to deterministically test reply races and interruption.

Completion criterion: two concurrent sessions can inspect and operate the same
Kernel without direct process-table access or cross-session request confusion.

### Milestone C: Add a read-only namespace model

- Define `NamespaceNode`, `NodeId`, `NodeKind`, attributes, lookup, open, read,
  list, release, and forget-like reference operations.
- Generate the proposed namespace solely from Catalog and Kernel snapshots.
- Define deterministic escaping for image references and capability names.
- Keep directory enumeration stable for each opened directory handle.

Completion criterion: an in-memory namespace test suite can browse images,
capabilities, and changing process state without mounting anything.

### Milestone D: Unify CLI and machine adapters

- Route CLI commands through `ControlGateway` instead of calling Kernel internals.
- Add a JSON Lines transport with request IDs and structured replies.
- Use the same gateway contract for external Human, rule-driven, and LLM-driven
  clients while keeping in-process Shell programs on the Event/Action contract.
- Add backpressure through a per-session in-flight limit.

Completion criterion: equivalent CLI and JSON requests produce equivalent replies
and audit records.

### Milestone E: Prototype a real FUSE adapter after 0.1 semantics stabilize

- Target Linux/libfuse3 only; keep Windows development supported through the
  in-memory namespace model.
- Place all FUSE bindings and errno translation in an optional adapter package.
- Start read-only. Add writable transaction nodes only after their semantics are
  proven by transport-neutral tests.
- Treat mount, unmount, signal handling, worker configuration, and connection loss
  as adapter/session concerns.
- Ensure unmount cannot silently cancel or reap SemShell processes.

Completion criterion: mounting and browsing the namespace requires no changes to
Kernel scheduling, process types, or software images.

## 7. Test plan

- One request produces exactly one terminal reply.
- Interrupt before, during, and after handler registration is never lost.
- Interrupted wait leaves the target process running.
- Disconnect after successful spawn does not erase or duplicate the new process.
- Session close drains or rejects every request handle within a deadline.
- Concurrent sessions cannot reuse or observe each other's request IDs as local
  handles.
- Namespace lookup and forget do not alter process ownership or reaping.
- Open directory views remain deterministic while the process table changes.
- Reaped targets make stale handles fail explicitly.
- Authority is checked on every mutation even when a node was previously visible.
- Unsupported operations return stable protocol errors; FUSE errno mapping is
  tested only in the optional adapter.

## 8. Explicit non-goals

- Replacing Process IPC with filesystem reads and writes.
- Treating files, directories, inodes, or mounts as new Kernel primitives.
- Treating namespace hierarchy as process ownership hierarchy.
- Making a FUSE mount the only way to operate SemShell.
- Coupling Kernel errors to Linux `errno` values.
- Adding libfuse or Python FUSE bindings to the base requirements before the
  optional Linux adapter is implemented.
- Optimizing caching, zero-copy I/O, or multithreaded FUSE throughput in this
  research phase.

## 9. Recommended ordering relative to the current TODO

Milestone A should be completed while closing cancellation semantics, because
request interruption and process cancellation must be distinguished together.
Milestone B belongs after Kernel cancellation and authority policy are stable.
Milestones C and D can then provide the common interface used by all operators.
Milestone E is post-0.1 experimental work and must not block the proof that all
software roles are equal Processes.
