# SemShell Core and Resource-Bridge Semantics

This document is the public normative summary for the version 0.1 core and the
minimal resource-bridge extension. Implementations may add diagnostics but
must preserve these rules.

## Core entities

- A ProcessImage is an immutable, versioned executable definition.
- A ProcessSpec is a single admission request and does not grant authority.
- A Process is one admitted execution with a unique monotonic PID.
- A Principal identifies the authority source and is not a Process.
- Authority is an immutable set of exact capability/scope permissions.
- A Capability describes a discoverable semantic interface; resolving it does
  not invoke software.

Scope comparison is exact in version 0.1; path hierarchy and wildcards are not
implicit.

## Activation

Each Process has one FIFO event mailbox and at most one active handler. The
Kernel delivers one Event and accepts exactly one returned Action per
activation. A READY Process has a deliverable Event. Cancelling, failing,
terminal, and reaped Processes are never activated.

Program exceptions become structured failed ProcessResults. Every admitted
Process publishes exactly one terminal result.

A resource continuation is inserted ahead of ordinary messages that queued
while the Process was waiting for that invocation. Those messages do not wake
the Process before the resource decision.

## Host resource invocation

The Host constructs an immutable ResourceRegistry before Kernel startup. A
binding pairs an opaque binding ID, factory-free metadata, a trusted mapping
from operation name to exact Permission, and a passive bridge. Guest code
cannot register, replace, unregister, or resolve bindings by descriptive data.

Every syntactically valid `InvokeResource` receives a monotonic Kernel-allocated
invocation ID, including immediate rejections. The Kernel derives caller PID,
Principal, and the Authority snapshot from the active Process record and
deep-freezes the JSON-like input. These authenticated fields are not Action
fields.

The Kernel rejects unknown bindings, unsupported operations, missing exact
Authority, malformed input, and exhausted bridge capacity before calling Host
bridge code. One Process may have at most one outstanding invocation. A
successful admission puts it in WAITING until exactly one
`ResourceCompleted` or `ResourceRejected` continuation wins.

Cancellation clears the pending continuation, records cancellation, and makes
bridge task cancellation advisory. A late bridge result cannot reactivate the
Process or expose its payload. Capacity remains occupied until the bridge task
actually settles.

Resource audit is append-only and metadata-only. It records identity,
operation, phase, required Permission, and stable error code, but never input,
Host paths, content, result payloads, bridge objects, or raw exceptions.

The minimal `read_text` contract accepts a portable relative path with `/`
separators and ASCII `[A-Za-z0-9._-]+` segments. Absolute paths, backslashes,
colons, empty, `.`, and `..` segments are invalid. Results are bounded UTF-8
text. The local proof also resolves an existing candidate below a fixed root;
it assumes a trusted temporary tree without concurrent adversarial symlink or
junction mutation.

## Ownership and waiting

An attached child has one owner. Ownership controls lifecycle cleanup; waiting
controls synchronization. Neither implies the other.

A Process may wait only for direct attached children. Wait-all, wait-any, and
empty waits are explicit. A satisfied wait emits at most one
`ChildrenCompleted` Event.

A parent cannot commit normal exit while it has active attached children.
Abnormal failure and tree cancellation perform bounded child cleanup first.

## IPC

Process Send derives the source PID from the currently running Process. Callers
cannot supply or forge it. Accepted messages have one authoritative mailbox
entry. Unknown, cancelling, terminal, and reaped targets reject ordinary IPC.

Console input is a Host-device Event delivered only through a console bridge
bound to one Process. It is not Process IPC.

## Spawn and authority

Before PID allocation the Kernel:

1. resolves an exact image or unambiguous capability;
2. validates image execute ACL;
3. validates the ProcessSpec;
4. evaluates requested authority against parent/caller authority, image
   declaration, system policy, and validated approval;
5. records an explainable authority decision;
6. creates the program and Process record.

A failed admission consumes no PID. Only READY, RUNNING, or WAITING parents may
create children.
Batch admission validates and freezes all Process metadata before allocating
any PID or publishing any Process record. A child cannot gain authority outside its
parent without a prior explicit policy approval. Partial grants are permitted
only when policy allows them and image minimum requirements remain satisfied.
Approval artifacts are validated against trusted Policy configuration; merely
constructing an artifact-shaped value cannot grant authority. Expiry,
revocation, signatures, and single-use behavior are outside version 0.1.

## Cancellation and completion

Cancellation, abnormal failure, and normal completion race through one
authoritative lifecycle decision. Once cancellation is accepted, the Kernel
owns an independent cleanup task; cancellation or failure of the requester
cannot abandon the target in `CANCELLING`. A concurrently failing child is
allowed to finish its already committed failure cleanup before its owner
finishes. Cancellation is idempotent after a terminal result exists.
Kernel shutdown waits for committed abnormal
failure cleanup in each root tree before cancelling its remaining live Processes.
Cleanup is bounded; non-cooperative cleanup may be retained only for diagnostics and
cannot reactivate the Process.

Completion recursively freezes the structured result and leaves an immutable
ProcessResult available for inspection and waiting. Reaping later removes the
terminal Process from the live Process Table; PIDs are never reused within one
Kernel lifetime.

## Catalog

Image versions are registered independently and never mutate running Processes.
Multiple providers may advertise one capability, but an ambiguous resolution
without an exact provider is rejected. An image version cannot be unregistered
while any live Process Table entry uses it.

## External control

The Host Control protocol has session/request identity and exactly one terminal
reply per admitted request. Request interruption and transport disconnect do
not imply Process cancellation or rollback of committed Kernel effects.

Control sessions are not Processes. Normal Operator execution uses Event/Action;
Host Control is limited to administration, observation, bootstrap, and tests.
Trusted Host bootstrap selects the initial Policy, Catalog, root Operator, and
any console binding. Remote authentication is outside version 0.1.

The local Control CLI maintains one session and allocates monotonically named
RequestIds after successful command parsing. Each admitted command produces one
terminal ControlReply and audit record. Parser failures are adapter outcomes,
consume no RequestId, and have no Kernel effect. `ListProcesses` is a read-only
external operation returning deterministic immutable Process snapshots.

The CLI cannot submit `SendMessage`: a ControlSession has no PID from which
authentic Process IPC could originate. Console input instead targets one
previously bound shell Process, and Process-to-Process IPC remains an Action.

External mutations require explicit unscoped administration permissions in
version 0.3: `control.process.cancel`, `control.process.reap`, and
`control.catalog.unregister`. The trusted local CLI bootstrap receives these
permissions. An ordinary Process may cancel itself or an attached descendant;
cancelling an unrelated Process requires exact
`Permission("process.cancel", str(target_pid))` authority.

## Role neutrality

The Kernel must not import, identify, or branch on HumanShell, RuleShell,
LLMShell, LLM, tool, memory, coordinator, or Agent roles. All running software
uses the same Process model.
