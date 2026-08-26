# SemShell 0.1 Semantics

This document is the public normative summary for version 0.1. Implementations
may add diagnostics but must preserve these rules.

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

A failed admission consumes no PID. A child cannot gain authority outside its
parent without a prior explicit policy approval. Partial grants are permitted
only when policy allows them and image minimum requirements remain satisfied.
Approval artifacts are validated against trusted Policy configuration; merely
constructing an artifact-shaped value cannot grant authority. Expiry,
revocation, signatures, and single-use behavior are outside version 0.1.

## Cancellation and completion

Cancellation, abnormal failure, and normal completion race through one
authoritative lifecycle decision. Cancellation is idempotent after a terminal
result exists. Cleanup is bounded; non-cooperative cleanup may be retained only
for diagnostics and cannot reactivate the Process.

Completion leaves an immutable ProcessResult available for inspection and
waiting. Reaping later removes the terminal Process from the live Process Table;
PIDs are never reused within one Kernel lifetime.

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

## Role neutrality

The Kernel must not import, identify, or branch on HumanShell, RuleShell,
LLMShell, LLM, tool, memory, coordinator, or Agent roles. All running software
uses the same Process model.
