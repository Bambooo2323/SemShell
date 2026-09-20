# Version 0.2 Candidate: Minimal Host Resource Boundary Proof

> Historical design context. Current guarantees are defined in
> [docs/semantics.md](../docs/semantics.md), with final evidence in the
> [design-edition validation record](../docs/design-edition-validation.md).
> The pre-removal Stage 3 implementation is recoverable from Git tag
> `complete-reference-20260915`; older contracts remain in ancestor history.
> Proposals and completion criteria below do not add active API guarantees.

## 1. Purpose

Version `0.2` should prove one additional architecture claim:

> A guest Process can use one explicitly exposed Host resource through a
> generic, authority-checked bridge without teaching the Kernel filesystem or
> other resource-specific semantics.

Version `0.1` proved that software roles can be flattened into Processes.
Version `0.2` should prove the smallest useful Host boundary. It is not a
complete sandbox, virtual filesystem, device model, or resource framework.

## 2. Falsifiable proof

The implementation succeeds only if all of these statements are observable:

1. Trusted bootstrap code installs one immutable binding for the entire Kernel
   lifetime.
2. One unchanged guest ProcessImage can invoke both an in-memory bridge and a
   local temporary-workspace bridge using the same `read_text` contract.
3. The Kernel derives PID, Principal, and an Authority snapshot from the active
   Process Control Block; the Action cannot supply these values.
4. Missing Authority rejects the invocation before bridge code runs.
5. Process cancellation winning the lifecycle race permanently suppresses late
   continuation delivery.
6. The Kernel contains no path, file, workspace, or `read_text` branch.

Anything not required for these six observations is deferred.

## 3. Responsibility boundary

| Component | Owns |
| --- | --- |
| Guest Process | Select the injected binding ID, operation, and structured input; handle the returned Event |
| Kernel registry | Immutable binding lookup, trusted permission mapping, pending invocation identity, and bridge reference |
| Process Kernel | Caller authentication, Authority snapshot/check, one-pending-call rule, task scheduling, completion/cancellation race, Event delivery, metadata-only audit |
| Host bridge | Operation-specific input validation, Host I/O, intrinsic size limits, containment checks, and Host-error normalization |

A bridge is passive Host capability plumbing. It has no PID, mailbox,
Principal, Authority, or orchestration role. It cannot spawn, wait, send Process
IPC, enqueue Events, or mutate Process state. It returns one outcome to the
Kernel. Guest services remain ordinary Processes and may later build richer
protocols over this primitive.

## 4. Minimal architecture

```text
Guest Process
    -> InvokeResource(binding_id, operation, input)
Process Kernel
    -> authenticate active PCB
    -> snapshot effective Authority
    -> resolve immutable binding
    -> validate trusted operation Permission
    -> record one pending invocation
HostResourceBridge
    -> return value or structured bridge error
Process Kernel
    -> win completion/cancellation race once
    -> ResourceCompleted | ResourceRejected
Guest Process
```

## 5. Core types

### 5.1 Binding

```text
ResourceBindingId
ResourceBindingDescriptor
```

`ResourceBindingId` is an opaque, runtime-local identifier and the canonical
Authority scope. It is unrelated to a PID and never reused within one Kernel
lifetime.

The immutable descriptor contains only:

- binding ID;
- resource kind;
- supported operation names;
- trusted required Permission for each operation;
- descriptive metadata with no Host location.

Version `0.2` has no guest binding discovery. Trusted bootstrap injects the
binding ID into the root task input. The descriptor exists for Host diagnostics
and tests. Operation schemas and runtime binding removal are deferred.

### 5.2 Action and continuation

```text
InvokeResource(binding_id, operation, input)

ResourceCompleted(invocation_id, binding_id, operation, value)
ResourceRejected(invocation_id, binding_id, operation, error)
```

The Kernel allocates `invocation_id`; the guest does not provide correlation or
idempotency identity in `0.2`. One admitted invocation produces at most one
continuation Event.

The Action carries no source PID, Principal, Authority, Host path, bridge
object, or callable.

### 5.3 Authenticated Host invocation

```python
class HostResourceBridge(Protocol):
    async def invoke(self, invocation: ResourceInvocation) -> object:
        ...
```

`ResourceInvocation` is created only by the Kernel after admission and contains:

- Kernel invocation ID;
- binding ID and operation;
- caller PID and Principal;
- a snapshot of effective Authority at invocation admission;
- structured operation input.

Constructing a similar value in guest code does not enter the trusted registry
or Kernel dispatch path.

## 6. Authority rule

The trusted bootstrap binding maps `read_text` to an exact Permission such as:

```text
Permission("workspace.read", "binding-1")
```

The scope is the immutable `ResourceBindingId`, never a display name or bridge
metadata. The registry freezes the operation-to-Permission mapping at startup.
Bridge code and guest code cannot mutate it.

The Kernel checks the PCB Authority snapshot before creating the bridge task.
The bridge separately validates the relative path and Host resource semantics.

```text
Kernel authorization     operation + immutable binding scope
Bridge validation        input type + relative path + resource limits
```

Binding metadata is Host-visible only in this proof, so discovery leakage does
not need a guest policy yet.

## 7. Invocation lifecycle

Version `0.2` permits at most one outstanding resource invocation per Process.
After returning `InvokeResource`, the Process enters WAITING with a dedicated
pending invocation record. Unrelated mailbox Events do not reactivate it until
the resource continuation is committed or the Process is cancelled.

Admission linearizes when the Kernel atomically records the pending invocation
against a still-running Process. Bridge code is not called before this point.

Completion and cancellation resolve once under the existing authoritative
lifecycle decision mechanism:

- If bridge completion wins while the caller remains eligible, the Kernel
  removes the pending record and enqueues exactly one continuation Event.
- If cancellation, failure, or another terminal decision wins first, the Kernel
  suppresses continuation delivery permanently.
- Cancelling the bridge task is advisory and does not imply Host rollback.
- Late completion creates only a bounded metadata audit record; result payloads
  are not retained.
- Kernel shutdown cancels bridge tasks best-effort and follows the same
  no-reactivation rule.

Write operations remain deferred because this lifecycle does not define Host
transaction or rollback semantics.

## 8. Stable errors and audit

Minimum error categories are:

- unknown binding;
- unsupported operation;
- authority denied;
- malformed input;
- resource not found;
- resource limit exceeded;
- bridge failure;
- invocation cancelled.

Audit records contain invocation ID, caller PID/Principal, binding ID,
operation, authorization decision, lifecycle outcome, reason, and timestamps.
They do not retain file contents or arbitrary result payloads.

## 9. Two interchangeable bridges

### 9.1 InMemoryResourceBridge

The fake bridge implements exactly the same operation contract as the local
bridge:

```text
read_text({"path": relative_path}) -> text
```

It stores a deterministic relative-path/text mapping, records authenticated
invocations, supports delayed completion for cancellation tests, and requires
no external resource.

### 9.2 LocalWorkspaceBridge

The local bridge exposes the same `read_text` operation over one explicitly
selected temporary directory. It must:

- reject absolute paths;
- reject lexical `..` escape;
- resolve paths only under its configured root;
- bound input path length and output bytes;
- normalize Host exceptions into stable bridge errors;
- never expose the Host root path to the guest;
- perform no writes.

The `0.2` containment claim assumes a trusted temporary tree without concurrent
adversarial symlink or junction mutation. Race-resistant handle-relative and
no-follow traversal is deferred and must not be implied by the demonstration.

## 10. Minimal guest and demo

Add one `workspace-reader` ProcessImage. It receives a binding ID and relative
path, returns `InvokeResource`, then exits with the `ResourceCompleted` text or
a normalized failure result.

The demo shows three paths:

```text
allowed read       -> expected text
missing Authority  -> rejected before bridge invocation
lexical path escape -> rejected by the bridge
```

The allowed path runs once with the fake bridge and once with the local bridge,
using the same ProcessImage and task input shape.

## 11. Implementation phases

### Phase 0: semantic closure

- Freeze binding identity, trusted permission mapping, and Kernel-lifetime
  ownership.
- Freeze the one-outstanding-invocation Process rule.
- Freeze admission and completion/cancellation linearization points.
- Freeze stable errors, bounds, and metadata-only audit.

### Phase 1: public values and fake bridge

- Add binding, invocation, outcome, error, and audit values.
- Add the HostResourceBridge protocol and startup-only registry.
- Implement InMemoryResourceBridge with `read_text` only.
- Add table-driven value and bridge contract tests.

### Phase 2: Kernel integration

- Add InvokeResource and continuation Events.
- Derive authenticated context from the active PCB.
- Enforce exact binding-scoped Authority before invoking bridge code.
- Add one pending invocation slot to Process runtime state.
- Resolve completion/cancellation once and suppress late delivery.

### Phase 3: local proof

- Implement LocalWorkspaceBridge over temporary roots only.
- Add absolute path, lexical traversal, missing file, and size-limit tests.
- Implement workspace-reader and the three-path demonstration.
- Assert that fake and local allowed runs produce the same guest result.

### Phase 4: documentation

- Extend public design, semantics, and security documents.
- Preserve the statement that in-process code can bypass bridges.
- Keep Docker and isolated executors as later containment layers.

## 12. Deferred features

The following are explicitly outside this proof:

- guest binding discovery;
- runtime unregister, draining, or rebinding;
- general operation schemas;
- caller-provided correlation IDs or idempotency keys;
- multiple concurrent invocations per Process;
- directory listing;
- write, rename, delete, watch, or transaction semantics;
- adversarial symlink/junction containment;
- FUSE or a mounted virtual namespace;
- network, secrets, subprocess, database, or model bridges;
- per-Process containers, WASM, or Docker orchestration;
- persistence and remote resource workers;
- a complete interactive CLI.

## 13. Completion criteria

The proof is complete when:

1. one unchanged workspace-reader ProcessImage works with both bridges;
2. the Kernel contains no resource-operation-specific branch;
3. missing Authority prevents the bridge invocation counter from changing;
4. absolute and lexical path escape are rejected inside a trusted temporary
   tree;
5. cancellation winning the race permanently suppresses late continuation;
6. every invocation has an explainable metadata-only audit record;
7. all tests are offline and touch only temporary resources;
8. Docker remains optional and no containment claim exceeds the implementation.

## 14. Recommended order after this proof

Only after this minimal contract is stable should the project consider:

1. a locked-down single-container runtime for coarse Host containment;
2. guest resource discovery and multiple binding types;
3. write-capable operations with explicit commit semantics;
4. a generic executor boundary for restricted subprocess/container execution.
