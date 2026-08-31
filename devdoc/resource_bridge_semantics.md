# SemShell Resource Bridge Semantics

## 1. Status and scope

This document freezes the candidate `0.2` semantics for one minimal Host
resource invocation path. It extends the `0.1` Process/Event/Action contract;
it does not replace Process IPC or the Host Control protocol.

The only demonstration operation is:

```text
read_text({"path": relative_path}) -> text
```

The Kernel remains resource-neutral. Any rule mentioning paths, text files, or
workspace containment belongs to the bridge implementation, not the Kernel.

## 2. Entities

### 2.1 ResourceBindingId

A `ResourceBindingId` is an opaque, non-empty identifier assigned by trusted
Host bootstrap. It is:

- unique and never reused within one Kernel lifetime;
- unrelated to Process PID, image ID, session ID, or Host path;
- the canonical exact scope used by resource Authority;
- safe to include in guest task input and diagnostic snapshots.

Version `0.2` has no guest binding discovery or alias resolution.

### 2.2 ResourceBindingDescriptor

A descriptor is immutable trusted metadata containing:

- binding ID;
- resource kind;
- supported operation names;
- one required `Permission` for each operation;
- optional descriptive metadata.

Descriptors never contain Host paths, file descriptors, sockets, bridge
objects, factories, or callables. They are available only through the trusted
Host diagnostic API in `0.2`.

The registry copies and freezes operation-to-Permission mappings at bootstrap.
Neither guest code nor bridge code may change authorization requirements.

### 2.3 ResourceBinding

A binding is the trusted registry entry pairing one descriptor with one
`HostResourceBridge` implementation. The binding is installed before Kernel
start and remains present until that Kernel stops.

There is no runtime register, unregister, drain, replace, or rebind operation in
`0.2`.

### 2.4 ResourceInvocationId

The Kernel allocates a positive, monotonic invocation ID for every
syntactically valid `InvokeResource` Action it evaluates, including immediate
rejections. IDs are never accepted from guest input and never reused within one
Kernel lifetime.

### 2.5 ResourceInvocation

A `ResourceInvocation` is a Kernel-created Host value containing:

- invocation ID;
- binding ID and operation;
- caller PID and Principal;
- immutable effective Authority snapshot;
- structured operation input.

It is passed only to the registered Host bridge. Constructing a similar Python
value does not register, admit, or execute an invocation.

### 2.6 HostResourceBridge

A bridge implements:

```python
class HostResourceBridge(Protocol):
    async def invoke(self, invocation: ResourceInvocation) -> object:
        ...
```

A bridge is passive Host plumbing. It has no PID, Principal, Authority,
mailbox, lifecycle ownership, or scheduling authority. It cannot enqueue guest
Events or mutate Process state. It returns one value or raises one bridge error;
the Kernel alone commits the outcome.

## 3. Process Action and Events

### 3.1 InvokeResource

```text
InvokeResource(binding_id, operation, input)
```

The Action validates that binding ID and operation are non-empty. It contains
no caller PID, Principal, Authority, invocation ID, Host location, bridge
object, or completion callback.

At Action evaluation the Kernel snapshots input into an immutable JSON-like
value. Version `0.2` accepts only `None`, booleans, finite numbers, strings,
lists/tuples of supported values, and string-keyed mappings of supported
values. Containers are recursively copied and frozen. Unsupported objects,
non-string mapping keys, cycles, and non-finite numbers receive immediate
`resource.malformed_input` rejection. A bridge never observes a caller-owned
mutable object.

### 3.2 ResourceCompleted

```text
ResourceCompleted(invocation_id, binding_id, operation, value)
```

This Event means bridge completion won the authoritative race and the caller
was still eligible for delivery.

### 3.3 ResourceRejected

```text
ResourceRejected(invocation_id, binding_id, operation, error)
```

This Event represents either an immediate Kernel rejection or a committed
bridge failure. Its `ProcessError.origin` distinguishes Kernel, Policy, and Host
failures.

One invocation ID produces at most one `ResourceCompleted` or
`ResourceRejected` Event. Cancellation may instead produce no resource
continuation because the Process itself reaches `CANCELLED`.

## 4. Trusted bootstrap and registry

Trusted Host bootstrap constructs the registry before `ProcessKernel.start()`.
The Kernel constructor receives the complete registry. Starting the Kernel
freezes it for the Kernel lifetime.

The registry owns:

- exact binding lookup;
- descriptor snapshots;
- trusted operation-to-Permission mappings;
- bridge implementation references.

The registry does not own Process state, pending calls, lifecycle decisions, or
Event delivery.

Unknown bindings are never resolved by resource kind, display name, metadata,
or fallback order.

## 5. Authority

Each binding operation declares one exact required Permission. For the minimal
workspace proof:

```text
binding ID: binding-1
operation:  read_text
permission: Permission("workspace.read", "binding-1")
```

The Kernel snapshots `pcb.context.authority` while evaluating the Action and
checks that the required Permission is present. It does not ask the guest or
bridge which Authority the caller has.

Authorization outcomes are:

- unknown binding: Kernel rejection;
- unsupported operation: Kernel rejection;
- missing Permission: Policy rejection;
- permitted: eligible for capacity admission.

An immediate rejection allocates an invocation ID, appends one
`ResourceRejected` Event, records an audit outcome, and returns the caller to
`READY`. It creates no pending record and never calls bridge code.

The bridge still validates operation-specific input. Kernel authorization does
not imply that a relative path or result is valid.

## 6. Admission and capacity

A Process may have at most one pending resource invocation. Returning a second
`InvokeResource` while one is pending is structurally impossible because a
pending caller is not activated.

The Kernel also has a positive `max_resource_invocations` limit. Capacity is
checked without waiting inside the Process activation:

- if capacity is unavailable, the Action receives immediate
  `ResourceRejected(resource.capacity_exceeded)`;
- if capacity is available, the Kernel atomically records the invocation as
  pending and consumes one resource slot.

Successful admission linearizes when the pending record is installed against a
still-`RUNNING` PCB. Only then may the Kernel create the bridge task.

After admission:

- the Process enters `WAITING`;
- the PCB records exactly one pending invocation ID and bridge task;
- ordinary queued mailbox Events do not reactivate the Process;
- public inspection exposes the pending invocation ID but not bridge objects,
  Host paths, inputs, or result payloads.

The resource task does not consume a normal Process activation slot after the
Action has returned.

Resource capacity counts live bridge tasks, not Process pending records. Each
admitted invocation owns one internal task record with a `slot_released` flag.
Only the common task-finalization path changes that flag and decrements the
capacity count. Clearing a Process pending record during cancellation does not
release capacity while a cancellation-resistant Host task still runs.

If bridge task construction or callback registration fails after admission,
the Kernel synchronously clears the matching pending record, finalizes the task
record and slot exactly once, appends
`ResourceRejected(resource.bridge_failure)`, and returns the Process to
`READY`. Bridge code has not run in this case.

## 7. Bridge outcome normalization

The bridge either returns a value or raises a stable `ResourceBridgeError`.
Unexpected bridge exceptions normalize to:

```text
ProcessError(
    code="resource.bridge_failure",
    origin=HOST,
    message="resource bridge failed",
)
```

Raw exception text, representation, arguments, traceback, type name, and Host
path are never copied into a Process Event or audit event. Expected
`ResourceBridgeError` values use a closed stable error code and its fixed public
message; arbitrary bridge-supplied messages or details are not trusted.

Minimum stable error codes are:

- `resource.unknown_binding`;
- `resource.unsupported_operation`;
- `resource.authority_denied`;
- `resource.capacity_exceeded`;
- `resource.malformed_input`;
- `resource.not_found`;
- `resource.limit_exceeded`;
- `resource.bridge_failure`;
- `resource.cancelled` for audit/diagnostics only.

The bridge owns input validation and intrinsic operation limits. The Kernel
does not interpret `path`, text encoding, file size, or returned content.

## 8. Completion linearization

Bridge task completion must re-enter the Kernel decision boundary. Completion
may commit only if all are true:

- the PCB still exists;
- its pending invocation ID exactly matches;
- its state is `WAITING`;
- no cancellation, failure, or terminal decision has won.

Completion linearizes when the Kernel, under its authoritative decision lock:

1. verifies those conditions;
2. clears the pending record;
3. releases the resource capacity slot;
4. appends exactly one `ResourceCompleted` or `ResourceRejected` Event;
5. moves the Process to `READY`.

The Process is scheduled only after this atomic decision is committed.

If the conditions do not hold, completion is late. The common task-finalization
path releases its slot exactly once and records metadata only. It never queues
an Event or changes Process state.

## 9. Cancellation and failure

Cancellation, failure, and resource completion share the existing Kernel
lifecycle decision lock.

If cancellation wins while a resource invocation is pending, the Kernel:

1. changes the Process to `CANCELLING`;
2. clears the PCB pending invocation, while the live task record retains its
   resource slot;
3. requests cancellation of the bridge task;
4. continues normal bounded Process cancellation and `program.stop()`;
5. commits the unique `CANCELLED` ProcessResult.

Bridge task cancellation is advisory. A Host operation may already have
committed and cannot be rolled back implicitly. A cancellation-resistant bridge
task may be retained as a draining diagnostic task under the existing bounded
cleanup policy.

If the bridge later returns or raises, its callback records only invocation ID,
caller identity, binding, operation, outcome, reason, and timestamps. It does
not retain operation input, returned text, or arbitrary exception objects. It
cannot reactivate the Process.

A Process cannot enter abnormal program failure while passively waiting because
its handler is not running. Kernel shutdown treats its pending invocation as
tree cancellation and follows the same rules.

Shutdown waits at most the existing positive `cancellation_timeout` for each
bridge task cancellation path. A task that does not finish is retained in the
Kernel draining-task set together with the minimum task record and bridge
reference required for safe finalization. `stop()` may return after the bound;
the task callback later releases its capacity slot and reference. Such a task
cannot enqueue an Event because its Process cancellation already won.

## 10. Mailbox behavior

Messages and ConsoleInput Events accepted while a Process waits for a resource
may remain queued, subject to existing mailbox rules. They do not satisfy the
resource wait and do not reactivate the Process.

If resource completion wins, its continuation is inserted at the front of the
mailbox so the Process handles the awaited outcome before unrelated queued
Events. If cancellation wins, no queued Event may reactivate the Process.

The current `0.2` prototype inherits the `0.1` unbounded in-memory mailbox.
There is therefore no full-mailbox branch for continuation insertion. Bounded
mailboxes, reservation, and overflow policy are deferred and this prototype
must not claim resistance to mailbox exhaustion.

## 11. Audit

Audit is an append-only sequence of immutable phase events rather than one
mutable record. An invocation may produce:

- one evaluated/admitted-or-rejected event;
- one cancelled event if Process cancellation wins;
- one completed or failed event if normal bridge completion wins;
- one late-completed or late-failed event if a suppressed task later settles.

Each audit event contains only the fields known at that phase:

- invocation ID;
- caller PID and Principal;
- binding ID and operation;
- required Permission when the binding and operation resolve;
- authorization outcome and reason;
- one phase timestamp;
- phase/outcome;
- normalized error code when applicable.

Audit events never contain operation input, Host paths, file contents, result
payloads, bridge objects, raw exceptions, exception types, or exception text.
Late outcome codes distinguish `late_completed` and `late_failed`; they do not
replace or mutate an earlier cancellation event.

## 12. Minimal read_text contract

Both fake and local bridges implement exactly:

```text
operation = "read_text"
input = {"path": <relative string>}
result = <UTF-8 text string>
```

The bridge rejects non-mapping input, missing/non-string paths, empty paths,
absolute paths, invalid portable syntax, lexical `..` escape, excessive path
length, missing resources, and output beyond the configured byte limit.

The guest path grammar is platform-independent:

- `/` is the only separator and a leading `/` is forbidden;
- `\`, `:`, NUL, empty segments, `.` segments, and `..` segments are forbidden;
- every segment contains only ASCII letters, digits, `.`, `_`, or `-`;
- total path length and segment count are positively bounded by bridge
  configuration.

Both bridges validate this exact grammar before lookup.

The local bridge resolves its configured root once, resolves the existing
candidate path before reading, and rejects a resolved candidate outside that
root. This rejects pre-existing escaping symlinks or junctions. The `0.2` proof
still assumes a trusted temporary tree without concurrent adversarial mutation
between resolution and open; race-resistant handle-relative traversal is
deferred. It performs no writes.

## 13. Required invariants

1. Binding identity is unrelated to PID and never resolved by descriptive data.
2. Guest code never supplies authenticated caller context or invocation ID.
3. Missing Authority prevents bridge invocation.
4. Each Process has at most one pending resource invocation.
5. Each live bridge task owns exactly one resource capacity slot, released once
   only when its task record finalizes.
6. Each invocation produces at most one resource continuation Event.
7. Completion and cancellation cannot both reactivate or complete the caller.
8. Late outcomes never retain payloads or reactivate Processes.
9. Bridge code cannot mutate Process state or enqueue Events.
10. The Kernel contains no resource-operation-specific behavior.
11. Fake and local bridges expose the same guest operation contract.
12. No Host containment claim exceeds the trusted-temporary-tree assumptions.
13. A bridge observes an immutable input snapshot, never guest-owned mutable
    input.

## 14. Deferred semantics

The following require a later protocol version:

- guest discovery and visibility policy;
- runtime register/unregister/rebind;
- multiple pending calls or batch invocation;
- caller correlation and idempotency keys;
- write commit, rollback, and transaction semantics;
- streaming and backpressure beyond a bounded single result;
- adversarial symlink-safe traversal;
- remote bridges, persistence, and reconnect;
- isolated executors and Docker containment.
