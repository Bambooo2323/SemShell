# SemShell Core Semantics

Status: normative draft for the `0.1` in-process runtime.

This document defines the observable behavior required from a compatible
SemShell kernel. It deliberately describes semantics before Python APIs. Class
and method names may evolve, but implementations must preserve the invariants
and transition rules defined here.

## 1. Scope

SemShell `0.1` is a single-host, single-Python-process, event-driven runtime.
It manages logical processes running on top of the host operating system. It
does not implement CPU preemption, virtual memory, a filesystem, a network
stack, durable recovery, or distributed execution.

The kernel recognizes only:

- process images and process specifications;
- processes and lifecycle states;
- capabilities and authorities;
- structured actions, events, messages, and results;
- ownership and wait relationships.

The kernel must not assign special execution semantics to LLMs, tools, agents,
memory services, coordinators, or shells. Those are user-space programs and
roles.

Normative terms such as **must**, **must not**, **should**, and **may** are used
in their usual specification sense.

## 2. Core entities

### 2.1 ProcessImage

A `ProcessImage` is an immutable, versioned software definition that the
kernel can instantiate. An image contains at least:

- a globally unique `image_id` within a catalog;
- a version;
- an entrypoint or program factory;
- zero or more provided capability specifications;
- zero or more declared authority requirements;
- an optional authority ceiling for admitted executions;
- an optional execute-principal ACL;
- optional input and output schemas;
- descriptive and trust metadata.

An image is not a running process and owns no runtime state. Replacing a
catalog entry must not mutate processes already created from the old image.

Image declarations describe possible requirements. They do not grant
authority to a process.

### 2.2 ProcessSpec

A `ProcessSpec` is a request to create one process from one image. It contains:

- an image reference or a capability resolution request;
- arguments and structured input;
- environment and logical working-directory metadata;
- requested authority;
- optional resource limits;
- ownership mode;
- caller-provided metadata.
- an optional prior approval artifact.

Requested authority is a request, not a grant. The kernel computes effective
authority during admission.

A `ProcessSpec` is single-use. Reusing the same values creates a different
process with a different PID.

### 2.3 Process

A `Process` is one runtime instance admitted from a `ProcessImage` and a
`ProcessSpec`. Kernel-owned process state includes:

- PID and optional owner PID;
- provenance, including the spawning PID where applicable;
- resolved image identity and version;
- principal and effective authority;
- lifecycle state;
- one event mailbox;
- ownership children;
- wait registration;
- timestamps and metadata;
- terminal result, if any.

Program-private state is owned by the program instance. It is not part of the
kernel process control record unless a future persistence contract explicitly
says otherwise.

### 2.4 Principal

A `Principal` identifies the source of authority for an execution, such as
`human:alice`, `service:ci`, or `system:kernel`. A principal is not a process and is
never scheduled.

A process executes on behalf of exactly one effective principal in `0.1`.
Delegation may reduce authority but does not silently change that principal.

### 2.5 Authority

`Authority` is a structured, immutable set of permissions carried by one
process execution. A permission consists of a capability name and an optional
scope. Examples include `fs.read` scoped to a workspace and `spawn` scoped to
specific images.

Authority must support deterministic subset and intersection operations.
Free-form natural-language permission checks are not valid kernel policy.
Version `0.1` uses exact scope matching; hierarchical or wildcard scope
semantics require a later, explicit policy contract.

For an ordinary child:

```text
child effective authority <= parent effective authority
```

Authority outside the parent set requires an explicit escalation decision by
an authorized policy or approval process. It must never be created merely
because a `ProcessSpec` requested it.

Image ACL and process authority are independent:

- image ACL determines who may inspect, modify, or execute an image;
- process authority determines what one admitted execution may do.

### 2.6 Capability

A `Capability` is a semantic interface advertised by one or more images. Its
specification contains at least a stable name, description, input schema,
output schema, declared side effects, required authority, and optional cost
metadata.

Resolving a capability selects an image; it does not invoke the image. If a
resolution request matches multiple providers and supplies no selection
policy, the `0.1` kernel must reject the request as ambiguous. It must not pick
a provider based on nondeterministic catalog order.

### 2.7 Message

A `Message` is structured IPC data with at least:

- a unique message ID;
- source PID;
- target PID;
- message kind;
- structured payload;
- optional correlation ID and metadata.

Conversation turns are one possible payload format, not a kernel primitive.

Messages and system lifecycle events share the process event mailbox after
delivery, but the kernel may distinguish their types. Cancellation is not an
ordinary message; it is lifecycle control as defined in Section 9.

### 2.8 Event

An `Event` is the sole input to one process activation. Events are immutable.
The initial event is `Started`. Other kernel-defined events include:

- `MessageReceived`;
- `ChildrenCompleted`;
- `Spawned`;
- `OperationCompleted`;
- `OperationRejected`;
- explicit user-space continuation events.

The kernel may add fields to events, but must not change their meaning based on
the semantic role of the receiving image.

### 2.9 Action

An `Action` is the sole output of one successful process activation. `0.1`
requires exactly one action per activation; action batches are deferred.

The core actions are:

- `Send`: submit one structured message;
- `Spawn`: request one or more child processes;
- `Cancel`: request cancellation of another process;
- `Detach`: remove lifecycle ownership from a direct child;
- `Wait`: register a wait condition;
- `Yield`: end the activation without registering a child wait;
- `Exit`: commit successful completion;
- `Fail`: commit failed completion.

The kernel distinguishes malformed Actions from rejected operations:

- an unsupported Action type or structurally malformed Action is a program
  protocol violation and fails the process;
- a well-formed Action that cannot be authorized or completed produces one
  `OperationRejected` continuation event and does not fail the caller.

Neither outcome may leave the process in `RUNNING`.

### 2.10 ProcessResult

A `ProcessResult` is the immutable terminal record exposed to waiters. It
contains:

- PID and resolved image identity;
- terminal state;
- optional structured result;
- optional structured error;
- start and completion timestamps;
- optional usage and diagnostic metadata.

A structured error contains at least:

- stable error code;
- human-readable message;
- origin (`program`, `kernel`, `policy`, or `host`);
- retryable flag;
- optional structured details;
- optional causal process or message ID.

Raw exception objects and tracebacks may be retained in private diagnostics,
but must not be the public error contract.

## 3. PID semantics

PIDs are positive, monotonically increasing integers scoped to one live Kernel
instance.

- PID `0` is reserved and is never assigned to a process.
- A PID is not reused during the lifetime of a Kernel instance.
- PIDs are not stable across Kernel restarts.
- A reaped PID remains reserved until that Kernel instance stops.
- External durable identity is outside the scope of `0.1`.

PID allocation identifies an admitted process. A failed catalog resolution or
failed authority admission does not consume a PID. Once a PID is returned by
`spawn`, the process is present in the Process Table and eventually obtains a
terminal result.

## 4. Lifecycle state machine

The states are:

```text
CREATED
READY
RUNNING
WAITING
CANCELLING
FAILING
EXITED
FAILED
CANCELLED
REAPED
```

`EXITED`, `FAILED`, and `CANCELLED` are completion states. `REAPED` is a final
administrative state. All four are terminal for scheduling and IPC.

### 4.1 Legal transitions

| From | To | Cause |
|---|---|---|
| `CREATED` | `READY` | Admission completes and `Started` is queued |
| `READY` | `RUNNING` | Scheduler begins one activation |
| `RUNNING` | `READY` | `Yield` queues an explicit continuation event |
| `RUNNING` | `READY` | An operation queues `Spawned`, `OperationCompleted`, or `OperationRejected` |
| `RUNNING` | `WAITING` | `Yield` without queued work, `Wait`, or waiting `Spawn` |
| `RUNNING` | `EXITED` | Valid `Exit` is committed |
| `RUNNING` | `FAILED` | Valid `Fail` is committed with no active attached children |
| `READY` | `FAILING` | Post-admission scheduler or host-executor failure |
| `RUNNING` | `FAILING` | Program exception, malformed Action, or host-executor failure |
| `WAITING` | `FAILING` | Post-admission scheduler or host-executor failure |
| `FAILING` | `FAILED` | Failure cleanup and descendant cancellation complete or expire |
| `READY` | `CANCELLING` | Cancellation is accepted before activation |
| `RUNNING` | `CANCELLING` | Cancellation wins before a terminal action commits |
| `WAITING` | `CANCELLING` | Cancellation is accepted while blocked |
| `CANCELLING` | `CANCELLED` | Cancellation cleanup completes or its deadline expires |
| `WAITING` | `READY` | A message or satisfied wait emits one deliverable event |
| `EXITED` | `REAPED` | Explicit reap |
| `FAILED` | `REAPED` | Explicit reap |
| `CANCELLED` | `REAPED` | Explicit reap |

All other transitions are illegal in `0.1`. In particular:

- `WAITING -> RUNNING` must pass through `READY`;
- a terminal process cannot return to an active state;
- `CANCELLING` cannot become `EXITED` or `FAILED`;
- `FAILING` cannot become `EXITED`, `CANCELLED`, or an active state;
- `REAPED` has no outgoing transition.

`CREATED` is not externally observable through a successfully returned PID;
admission changes it to `READY` before `spawn` returns.

### 4.2 State invariants

- A `READY` process has at least one deliverable event.
- A `RUNNING` process has exactly one active handler invocation.
- A `WAITING` process has no deliverable event. It may have a registered wait
  condition, or may be passively waiting for a message.
- A `CANCELLING` process cannot begin another program activation.
- A `FAILING` process cannot begin another program activation and already has
  an immutable pending structured error.
- A completion-state process has exactly one `ProcessResult`.
- A `REAPED` process is absent from the active Process Table, although the PID
  remains reserved.

## 5. Activation semantics

The Program interface is conceptually:

```python
async def handle(context: ProcessContext, event: Event) -> Action:
    ...
```

There is no semantically distinct `start()` callback. Creation queues a
`Started` event, which is handled through the same activation path as every
other event.

One activation follows this sequence:

1. The scheduler selects a `READY` process.
2. The kernel atomically removes exactly one deliverable event from its
   mailbox and changes `READY -> RUNNING`.
3. The kernel invokes the program handler once with that event.
4. The handler returns exactly one Action, raises an exception, or is cancelled
   by lifecycle control.
5. Unless cancellation has already won, the kernel validates and applies the
   Action, then leaves `RUNNING` through exactly one legal transition.

The same process must never have overlapping handler invocations. Different
processes may be activated concurrently.

Mailbox order is FIFO for events committed sequentially by the same sender.
No total ordering is promised for events committed concurrently by different
senders.

### 5.1 Continue, Yield, and Wait

`Continue` is not part of the `0.1` Action protocol. It is intentionally
excluded because an implicit continuation can create a `READY` process with no
event and hides the boundary between two activations.

`Yield` ends the current activation without registering a child wait:

- `Yield(next_event=E)` queues the explicit user-space continuation event `E`
  and changes the process to `READY`.
- `Yield()` changes the process to `READY` only if another event is already
  deliverable; otherwise it changes the process to passive `WAITING`.

`Wait` registers an explicit synchronization condition. A waiting process is
woken only by a single `ChildrenCompleted` event for that registration, or by
accepted cancellation. Ordinary messages may be queued while a child wait is
active, but do not satisfy or bypass that wait.

Programs that want to continue immediately must provide an explicit
continuation event. The kernel must never schedule a `READY` process against an
empty mailbox.

## 6. Ownership semantics

Ownership controls lifecycle responsibility. Waiting controls synchronization.
They are separate relationships.

### 6.1 Attached processes

An attached process has exactly one owner PID. It appears in the owner's child
set and is included in tree cancellation.

An attached child's completion does not automatically terminate or wake its
owner. The kernel records the result, but emits no unsolicited `ChildExited`
event in `0.1`. Wake-up occurs only if the owner has a matching wait
registration. An owner may register a later Wait and consume the recorded
completion result.

### 6.2 Detached processes

A detached process has no owner PID and is a lifecycle root. The kernel records
its `spawned_by_pid` as provenance, but provenance does not imply ownership.

A detached process:

- is not cancelled when its spawning process is cancelled or exits;
- may be waited on only through a future non-child observation API, which is
  outside the core `0.1` child-wait contract;
- retains the principal and only the authority admitted at spawn time.

Detachment is an explicit `ProcessSpec` choice and may require policy approval.

### 6.3 Owner completion

Normal `Exit` or `Fail` does not implicitly cancel attached children in `0.1`.
Before committing a terminal action, a process with active attached children
must choose one of the following explicitly:

- wait for them;
- cancel them;
- detach them, if policy permits.

An `Exit` or `Fail` that would orphan attached children is a well-formed but
rejected operation. The kernel queues `OperationRejected`, moves the owner to
`READY`, and leaves the children unchanged. The owner can then wait, issue a
`Cancel` Action, or issue a policy-authorized `Detach` Action.

Tree cancellation is the exception: it recursively cancels attached
descendants before the target commits `CANCELLED`.

If the owner cannot make that explicit choice because its handler raises, its
Action is malformed, or host execution fails, the kernel commits the abnormal
failure decision by moving the owner to `FAILING`. It then performs tree
cancellation of active attached descendants and moves `FAILING -> FAILED` when
cleanup completes or reaches its deadline. Abnormal failure therefore cannot
orphan attached children.

## 7. Wait semantics

`Wait` in `0.1` may target only direct attached children of the caller.
Unknown, detached, non-child, or reaped PIDs cause `OperationRejected`.

A wait registration contains an immutable target set and one mode:

- `all`: satisfied when every target has a completion result;
- `any`: satisfied when at least one target has a completion result.

Rules:

1. Already completed, unreaped children count toward satisfaction.
2. An empty target set is immediately satisfied.
3. Immediate satisfaction queues exactly one `ChildrenCompleted` event and
   moves the process to `READY`; it does not invoke the handler recursively.
4. `all` returns results for every target in ascending PID order.
5. `any` returns all target results already committed at the instant the
   kernel satisfies the registration, in ascending PID order. It guarantees at
   least one result but not exactly one under concurrent completion.
6. Once satisfied, the registration is removed before its event is queued.
7. Later child completions cannot emit another `ChildrenCompleted` event for
   the removed registration.
8. `any` does not cancel unfinished children. A coordinator must explicitly
   request cancellation if it implements first-winner behavior.
9. A process may have at most one active wait registration in `0.1`.

Child completion records remain inspectable until the child is reaped. Reaping
a child that is referenced by an active wait is forbidden.

## 8. Message delivery semantics

`0.1` provides in-memory, at-most-once delivery while one Kernel instance is
alive.

- A successful `Send` means the kernel accepted and enqueued the message once.
- It does not mean the recipient processed the message.
- A send to an unknown, cancelling, terminal, or reaped PID is rejected.
- The kernel does not retry a message after handler failure.
- Messages are lost if the Kernel process stops.
- The kernel provides no deduplication across separate `Send` actions.
- Correlation IDs are application-visible metadata, not delivery guarantees.

Each process has one authoritative event mailbox. The kernel must not copy the
same message into parallel inbox and pending-event queues.

An event is **deliverable** when it is eligible to be removed for the next
activation. Without an active wait registration, the oldest mailbox event is
deliverable. With an active wait registration, ordinary mailbox events are
gated and no event is deliverable until the wait is satisfied. At satisfaction,
the kernel removes the registration and inserts exactly one
`ChildrenCompleted` event ahead of the gated events. That completion event is
then deliverable.

While a process has an active child wait, accepted ordinary messages remain
queued behind the wait gate. When the wait is satisfied, its
`ChildrenCompleted` event is delivered before messages that arrived while the
gate was active or while the preceding activation was running. Registering the
wait does not discard, reject, or reorder those ordinary messages relative to
one another; it only places the single wait-completion event ahead of them.
After the process handles that completion event, the remaining messages become
deliverable in their existing FIFO order.

## 9. Cancellation semantics

Cancellation is a Kernel lifecycle operation, not ordinary IPC. It has higher
priority than beginning a new activation.

The public operation accepts a target and a mode:

- `self`: cancel only the target, valid only when it owns no active attached
  children;
- `tree`: cancel the target and all attached descendants.

Cancellation is idempotent for `CANCELLING` and completion-state targets. A
request against `CANCELLING` observes the existing cancellation operation; a
request against `EXITED`, `FAILED`, or `CANCELLED` returns the existing terminal
result without changing state. A request against `FAILING` is rejected because
an abnormal failure decision has already won and no terminal result exists yet.

`tree` cancellation proceeds from leaves toward the target for cleanup and
result commitment. The kernel marks every selected non-terminal process
`CANCELLING` before awaiting program cleanup, preventing new activations and
new child creation within the selected subtree.

Program cleanup is best-effort and bounded by a kernel deadline. A cleanup
exception or timeout is recorded in cancellation diagnostics but does not
change the terminal state from `CANCELLED` to `FAILED`.

If the target is `RUNNING`, the kernel marks it `CANCELLING`, requests
cooperative cancellation of the active handler task, and ignores any Action it
later returns. Cleanup begins after the handler task acknowledges cancellation
or its deadline expires. A task that ignores cancellation is retained only for
draining and diagnostics; it can no longer mutate kernel state or publish an
Action. The kernel must keep a strong reference to it until it finishes.

A `self` cancellation request against a process with active attached children
is rejected. Callers must use `tree` or explicitly detach/cancel the children
first. This rule also applies when cancellation is requested through a `Cancel`
Action. Kernel shutdown always uses `tree` at lifecycle roots.

### 9.1 Cancellation versus completion

The kernel serializes terminal decisions. The first committed lifecycle
decision wins:

- If `Exit` or `Fail` commits first, a later cancel is a no-op and returns the
  existing result.
- If cancellation changes the process to `CANCELLING` first, a concurrent or
  late `Exit`/`Fail` action is discarded and the process becomes `CANCELLED`.
- If abnormal failure changes the process to `FAILING` first, later
  cancellation and returned Actions are ignored and the process becomes
  `FAILED` after bounded cleanup.
- Exactly one terminal result is published.

Cancellation of a child produces a normal structured child result with state
`CANCELLED`. It therefore satisfies `all` and `any` waits just like `EXITED` or
`FAILED`.

Ordinary messages accepted before cancellation may remain in diagnostics but
must not reactivate the process. Messages submitted after cancellation is
accepted are rejected. Late child completions may update their own results but
must not wake a cancelling or terminal owner.

## 10. Spawn and authority admission

Spawn is evaluated in this order:

1. Resolve an exact image or an unambiguous capability provider.
2. Validate image execute ACL.
3. Validate the ProcessSpec and ownership mode.
4. Compute effective authority from image declaration, parent authority,
   system policy, and any prior explicit approval.
5. Reject unresolved authority escalation; do not block inside `spawn` waiting
   for human interaction.
6. Create the program instance and process control record. Image factories
   must be side-effect free; externally visible work begins only when handling
   `Started`.
7. Allocate a PID, establish ownership, queue `Started`, and admit the process
   as `READY`.

If steps 1-6 fail, no process is admitted and no PID is consumed. After step 7,
the child must eventually publish a terminal result, including when scheduling
or host execution later fails.

Interactive approval is modeled in user space: a process receives a denied or
pending admission result, communicates with an approval process, then submits
a new Spawn request carrying the resulting authorization artifact.

The policy must validate that artifact against trusted policy state. Merely
constructing an artifact-shaped value does not grant authority. Every
evaluation records the principal, requester PID when present, image,
requested and granted authority, decision, reason, and approval identity.

## 11. Action-specific outcomes

### 11.1 Send

After a successful `Send`, the sender behaves like `Yield()`: it becomes
`READY` if another event is deliverable, otherwise passive `WAITING`.
`Send` does not imply waiting for a reply. Request/reply is a user-space
protocol built with messages and correlation IDs.

If the target does not exist or cannot accept messages, the kernel queues one
`OperationRejected` event for the sender and moves it to `READY`.

### 11.2 Spawn

`Spawn` may contain one or more ProcessSpecs and declares whether the caller
wants an immediate child wait:

- without wait, child PIDs are returned in a `Spawned` continuation event;
- with wait, the kernel registers a wait over successfully admitted children
  and later emits `ChildrenCompleted`; the Spawn Action must specify `all` or
  `any` mode.

Multi-child Spawn admission is all-or-nothing before PID allocation in `0.1`.
If any spec fails validation or admission, no child is created. Host failures
after admission are represented as child failures, not rollback.

A Spawn requesting an immediate wait must contain only attached ProcessSpecs.
A wait over a detached or mixed attached/detached Spawn is rejected atomically
before PID allocation. A non-waiting Spawn may create either ownership mode.

A rejected Spawn queues one `OperationRejected` event and moves the caller to
`READY`. Events already in the caller mailbox do not invalidate a waiting
Spawn; they are gated by the new wait registration under Section 8.

### 11.3 Cancel

`Cancel` requests `self` or `tree` cancellation of the caller or one of its
attached descendants. An unrelated target requires exact
`Permission("process.cancel", str(target_pid))` authority. It is an ordinary
user-space Action even though the accepted operation uses Kernel lifecycle
control.

If accepted, the caller receives one `OperationCompleted` continuation event
after the lifecycle request has been committed and every active selected target
is either already `CANCELLING` or has been moved there. This event does not
assert that cleanup has finished. A terminal target is also an idempotent
success; `OperationCompleted` then includes its existing ProcessResult. An
owner that needs terminal child results after active cancellation must
subsequently use `Wait`.

A target in `FAILING`, an unauthorized target, or an otherwise invalid request
produces `OperationRejected`. If the selected `self` or `tree` cancellation set
contains the caller anywhere in that set, no continuation event is produced
because the caller moves from `RUNNING` to `CANCELLING` as the Action is
applied.

Acceptance transfers cleanup ownership to an independent Kernel task. The
requesting activation may be cancelled without abandoning any accepted target
in `CANCELLING`. If abnormal owner cleanup encounters a child whose `FAILING`
decision already won, it waits for that child's bounded cleanup and terminal
result before completing the owner failure.

### 11.4 Detach

`Detach` may target only a direct, active, attached child and requires policy
authorization. On success, the kernel removes the ownership edge, makes the
child a lifecycle root, records the former owner as provenance, and queues one
`OperationCompleted` event for the caller. Detach does not alter the child's
already-admitted principal or authority. Rejection produces
`OperationRejected`.

### 11.5 Wait

`Wait` follows Section 7. It has no message-delivery side effect.

### 11.6 Yield

`Yield` follows Section 5.1. It is the only no-side-effect control Action.

### 11.7 Exit and Fail

`Exit` and `Fail` attempt to commit a terminal result. They produce
`OperationRejected` when the process still owns active attached children, as
defined in Section 6.3.
`Fail` requires a structured error or an error value that the kernel can
normalize into one.

## 12. Reaping and inspection

Completion and reaping are separate:

- completion recursively freezes the structured result, publishes an immutable
  ProcessResult, and leaves the process
  inspectable;
- reaping removes the process control record from the active Process Table.

Only a completion-state process may be reaped. Reaping is forbidden while:

- an active wait registration references the process;
- the process still owns attached children;
- the kernel is publishing its result to an owner.

Inspection returns immutable snapshots. User-space code must not receive
mutable Process Table entries or mailbox objects.

## 13. Kernel shutdown

Graceful Kernel shutdown stops new admission, performs tree cancellation on
all lifecycle roots, waits for bounded cleanup, and then stops scheduling.
Detached processes are roots and are included.

Shutdown does not imply persistence. Any unconsumed messages and reaped or
unreaped process records disappear when the host process ends.

## 14. Required invariants

Every compatible `0.1` implementation must preserve these invariants:

1. The kernel contains no role-specific branch for LLM, tool, agent, memory,
   coordinator, or operator processes.
2. Every running entity is represented by exactly one Process.
3. A Process comes from exactly one resolved ProcessImage and one ProcessSpec.
4. A process has at most one owner and at most one active wait registration.
5. Ownership never implies waiting, and waiting never changes ownership.
6. A child cannot obtain authority outside its parent without explicit,
   auditable escalation.
7. A `READY` process always has a deliverable event.
8. A process has at most one active handler invocation.
9. Each admitted process publishes exactly one terminal ProcessResult.
10. A terminal or cancelling process is never activated again.
    A failing process is likewise never activated again.
11. A wait registration emits at most one completion event.
12. Cancellation and normal completion cannot both win.
13. The same IPC message has one authoritative mailbox entry.
14. CLI commands, LLM decisions, and program decisions reach the kernel through
    the same structured operations.

## 15. Conformance test table

At minimum, an implementation must test:

| Area | Required cases |
|---|---|
| PID | monotonic allocation, no reuse after reap, no allocation on rejected admission |
| Lifecycle | every legal transition, `FAILING` cleanup, and representative illegal transitions |
| Activation | one event per activation, no reentrancy, exception becomes structured failure |
| Yield | explicit continuation, passive wait, queued-event wake-up |
| Ownership | attached propagation, detached survival, orphan prevention |
| Wait | all, any, empty, already-complete, non-child rejection, single wake-up |
| IPC | FIFO per sequential sender, unknown/terminal target rejection, no duplicate queue entry |
| Cancellation | self, tree, cleanup timeout, cancel/exit race, cancelled child satisfies wait |
| Operations | Send/Spawn/Cancel/Detach success and rejection continuations |
| Spawn | exact image, capability resolution, ambiguous provider, all-or-nothing multi-spawn |
| Authority | subset inheritance, reduction, unauthorized escalation, audited approval artifact |
| Result | exactly-once terminal publication, structured error normalization, immutable result |
| Reap | active-process rejection, active-wait rejection, terminal removal, PID reservation |
| Shutdown | admission rejection, root cancellation, bounded cleanup, no remaining scheduler tasks |

## 16. Deferred questions

The following are intentionally outside the `0.1` contract rather than left
ambiguous:

- durable process identity and restart recovery;
- cross-kernel messaging and remote ownership;
- observing or waiting on arbitrary non-child processes;
- multiple concurrent wait registrations;
- action batches and transactional multi-action commits;
- message retry, acknowledgement, deduplication, and backpressure;
- subprocess signals and streaming byte channels;
- resource accounting and supervisor restart policies;
- capability provider ranking or automatic semantic selection.
