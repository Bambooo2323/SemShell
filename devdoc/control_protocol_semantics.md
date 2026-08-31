# SemShell Control Protocol Semantics

Status: normative draft for Milestone 4.1  
Target: SemShell 0.1 control boundary  
Depends on: [`semantics.md`](./semantics.md)

## 1. Scope

This document defines a transport-neutral request/reply boundary for external
control of one live SemShell Kernel. It is suitable for an in-memory client, the
CLI, JSON Lines, a local socket, and a future FUSE adapter.

It does not replace Process events and Actions. A running `ProcessProgram` still
handles one Event and returns one Action. The control protocol is the northbound
boundary used by clients that are not currently executing inside a Process
activation. Implementations should share Kernel operation logic beneath these
two boundaries, not translate an in-process Action into a fake external session.

The protocol adds no filesystem, inode, path, mount, LLM, Tool, Agent, or Shell
primitive to the Kernel.

## 2. Layering

```text
external client
    -> transport adapter
    -> ControlSession
    -> ControlGateway
    -> public Kernel operation
    -> Process Kernel

running ProcessProgram
    -> ProcessAction
    -> the same Kernel operation logic
    -> Process Kernel
```

The `ControlGateway` may retain session and request bookkeeping. It must not
read or mutate `ProcessControlBlock`, mailboxes, scheduler tasks, or other Kernel
internals directly.

## 3. Core entities

### 3.1 SessionId

`SessionId` is an opaque, non-empty identifier unique among sessions created by
one live gateway. It is not a PID, Principal ID, security credential, or durable
identity. A gateway restart begins a new identity domain.

### 3.2 RequestId

`RequestId` is an opaque, non-empty identifier supplied by the client and unique
within one session. The pair `(SessionId, RequestId)` identifies one request.

Reusing a RequestId is a session protocol violation. The duplicate is not
admitted and cannot execute. Because the original request may already have its
one terminal reply, the gateway reports this violation through the transport's
session-error channel and may close the session; it must not emit a second
terminal reply for the reused ID.

Request IDs do not provide retry idempotency across sessions in 0.1.

### 3.3 ControlContext

`ControlContext` is immutable session-derived caller context containing:

- SessionId;
- effective Principal;
- maximum delegated Authority;
- optional audit metadata established during session admission.

Client request payloads cannot override these fields. A transport may carry
authentication material during session admission, but admitted requests receive
only the resulting ControlContext.

### 3.4 ControlSession

A `ControlSession` owns:

- one ControlContext;
- negotiated protocol version and optional features;
- the set of used RequestIds;
- bounded in-flight request handles;
- delivery of terminal replies;
- interruption and close state.

A session is not a Process and owns no process lifecycle edge. Session closure
does not mean Kernel shutdown, parent exit, Process cancellation, detachment, or
reaping.

### 3.5 RequestHandle

A `RequestHandle` is gateway-owned state for one admitted request. Its externally
observable states are:

```text
ADMITTED -> DISPATCHED -> REPLIED
    |            |
    +------------+-----> REPLIED (INTERRUPTED)
```

`REPLIED` is terminal. Internally, an operation that committed before an
interrupt or disconnect may continue draining after the handle reaches REPLIED.
Such a draining task has no right to publish another reply.

The handle owns a one-shot reply gate, an interruption flag, and, for mutating
operations, an operation task. Reading and registering interest in interruption
must be atomic with respect to setting that flag, so an interrupt received while
the handle is ADMITTED cannot be lost. Payload and capacity rejection transition
directly from ADMITTED to REPLIED without dispatch.

### 3.6 ControlRequest

Every request contains exactly:

- protocol version;
- RequestId;
- one typed operation and its payload;
- optional request metadata that has no authorization effect.

Session identity and caller authority are provided by the session, not repeated
as trusted request fields.

### 3.7 ControlReply

Every admitted request publishes exactly one terminal reply containing:

- protocol version;
- RequestId;
- operation name;
- terminal status;
- optional typed value;
- optional `ControlError`;
- optional audit/diagnostic metadata.

Terminal status is one of:

- `SUCCEEDED`: the operation reached its defined success point;
- `REJECTED`: validation, authorization, state, or operation execution rejected
  the request before its success point;
- `INTERRUPTED`: interruption won the reply gate before a terminal operation
  reply was published.

Exactly one of value or error may be present, except that a successful operation
whose result type is empty has neither. `REJECTED` and `INTERRUPTED` require an
error. Transport framing failures that prevent request admission are not
ControlReplies.

### 3.8 ControlError

A ControlError contains a stable protocol code, human-readable message, origin,
retryable flag, and structured details. Initial origins are `protocol`,
`gateway`, `kernel`, `policy`, and `transport`.

Python exception class names, tracebacks, and platform `errno` values are not
stable protocol codes. Adapters may map a ControlError to transport-native errors
without changing the underlying error.

## 4. Request admission

For every decoded request, a session performs these steps in order:

1. Reject at the session-error boundary if the session is not open.
2. Validate framing and the supported protocol version.
3. Under the session lock, verify that RequestId is unused, reserve it permanently,
   create its RequestHandle in ADMITTED, and install its one-shot reply gate. This
   is the request-admission linearization point.
4. Validate the typed payload without causing Kernel side effects. Rejection
   transitions the handle directly from ADMITTED to REPLIED.
5. Reserve one in-flight dispatch slot. If none is available, publish REJECTED
   with `gateway.busy`; a capacity-rejected request never owns a slot.
6. Transition ADMITTED to DISPATCHED and invoke the operation with the session's
   immutable ControlContext.

Steps 1-2 and a reused ID at step 3 happen before request admission and therefore
produce a transport/session error rather than a ControlReply. From successful
completion of step 3 onward, every outcome, including payload or capacity
rejection, goes through the handle's one-shot reply gate. A rejected RequestId
remains used. Steps 3-5 contain no suspension point; session close or interrupt
is observed immediately after this admission section and competes through the
same reply gate before dispatch.

The in-flight slot is released when the handle reaches REPLIED, even if a
committed underlying operation is retained temporarily for draining.

## 5. Reply commitment

The one-shot reply gate serializes normal completion, rejection, interruption,
and session closure. The first event to commit a terminal reply wins. All later
attempts are discarded and recorded as diagnostics.

The reply gate is not the Kernel commit point. Every mutating operation has a
linearization point defined in Section 9. The gateway invokes each mutating
public Kernel operation in a dedicated task and shields that task from request
handler cancellation. Therefore:

- interruption before dispatch prevents the Kernel call;
- once dispatch invokes a mutating Kernel call, interruption may win the reply
  gate but cannot abort that call partway through;
- the Kernel call may subsequently commit or reject, and its outcome is audited
  but cannot publish a second reply;
- ordinary read-only snapshot operations may be cancelled without shielding
  because they have no Kernel side effect.

This deliberately creates an uncertain client outcome when interruption races a
dispatched mutation. Cross-session outcome recovery is deferred; the protocol
does not claim otherwise.

Reply delivery and reply commitment are distinct:

- commitment means the gateway fixed the unique terminal reply;
- delivery means the transport successfully conveyed it to the client.

A failed delivery never reopens the gate and never rolls back a Kernel change.
The gateway may retain the committed reply for diagnostics until session cleanup,
but 0.1 does not promise reconnection or replay.

## 6. Interruption

`interrupt(RequestId)` is session control, not a ControlRequest and not a Process
cancel operation. It targets only an admitted, unreplied request in the same
session.

- Unknown, non-admitted, or already replied IDs produce no new ControlReply.
- Interrupting twice is idempotent.
- If interruption wins the reply gate, the request replies INTERRUPTED once.
- If the operation reply committed first, interruption has no effect.
- The gateway requests cooperative cancellation of the request handler after
  interruption wins. A separately shielded mutating operation task continues to
  its Kernel outcome; a read-only handler may stop immediately.

An adapter must not expose interruption as `cancel_process`. Conversely,
`CancelProcessRequest` cannot interrupt the request that submitted it unless the
client separately interrupts that RequestId.

## 7. Session close and disconnect

Session close has two phases:

1. stop request admission;
2. interrupt every admitted unreplied request and drain handler tasks up to a
   configured deadline.

Each unreplied handle commits INTERRUPTED if closure wins its reply gate. A
transport disconnect may make delivery impossible, but the reply remains
logically committed for invariants and audit.

After the drain deadline, the gateway transfers non-finished shielded operation
tasks to a gateway-level drain set and retains strong references until they
finish or Kernel shutdown makes completion impossible. Drain-set tasks cannot
publish another reply. A bounded drain set is required before any remote mutation
adapter is enabled; exceeding it stops new mutating admission with `gateway.busy`.
Already committed Kernel effects remain committed.

Closing a session never implicitly cancels, detaches, or reaps a Process created
or observed by that session. A client that wants session-owned lifecycle behavior
must explicitly create a supervisor Process and use attached process ownership.

## 8. Authority rules

The session's Authority is a ceiling, not an automatic grant to newly spawned
Processes.

- Requested root-process authority must be a subset of session Authority.
- A request to operate on an existing Process requires the relevant scoped
  permission under system policy.
- Visibility through a CLI listing or future namespace does not grant mutation
  authority.
- Gateway checks provide early rejection, but the Kernel operation remains the
  authoritative policy enforcement point. The gateway must not be the only
  security boundary.
- Every admitted mutating request emits an audit record containing session,
  Principal, operation, target, requested authority where applicable, outcome,
  and policy reason.

Until Kernel-side authorization exists for an operation, exposing that mutation
through a remotely reachable adapter is forbidden. An in-process development
adapter may be used only when explicitly marked non-security-enforcing.

## 9. Initial operation set

### 9.1 ListImages

Input: optional exact filtering metadata defined later.  
Success point: an immutable, deterministically ordered tuple of
`ProcessImageDescriptor` values is created. Descriptors contain metadata but
never executable factories or other host callables.  
Interruption after snapshot creation does not alter Catalog state.

### 9.2 ResolveImage

Input: exactly one exact image reference or capability name.  
An exact provider reference may accompany a capability name.  
Success point: one immutable factory-free image description is resolved.  
Ambiguous capability resolution is REJECTED, never selected implicitly; a
caller-selected provider must advertise the requested capability.

### 9.3 UnregisterImage

Input: one exact image reference.  
Success/linearization point: the exact image is removed from the Catalog and all
capability provider indexes after the Kernel confirms no Process remaining in the
live Process Table uses that version.  

The operation is a shielded mutation. Interruption after dispatch may produce an
uncertain client outcome and a late audit record; it never partially edits
provider indexes. Registering a host executable factory is intentionally not an
external Control operation. Trusted host code may load/register a ProcessImage;
install, download, and compilation remain future user-space package-manager work.

### 9.4 SpawnProcesses

Input: one or more ProcessSpecs.  
Success point: Kernel admission commits and returns the admitted PIDs.  

Before dispatch, requested authority must fit within ControlContext Authority.
An external session has no PID, so this operation creates lifecycle roots and
cannot supply a parent PID. Attached child creation remains a `Spawn` Action of a
running Process. A future spawn-under/adoption operation requires separate,
explicit authorization semantics.

The linearization point is insertion of the fully admitted Process into the
Process Table with its reserved PID, ownership edge, and initial event. If
interruption wins before dispatch, no Process is created. Once the gateway invokes
the shielded Kernel spawn operation, interruption can no longer promise that no
Process is created. If admission commits, the Process remains admitted even when
INTERRUPTED wins the reply gate before the PID reaches the client. The audit log
must record `(SessionId, RequestId, PID)`. Automatic cancellation would violate
the separation between request lifetime and Process lifetime.

Cross-session idempotent spawn and outcome lookup are deferred. After disconnect,
0.1 provides no guaranteed client recovery for an uncertain PID; deployments may
inspect implementation audit records, but portable clients must not blindly retry.

### 9.5 WaitProcess

Input: one PID and optional gateway-side timeout.  
Success point: the target's immutable terminal ProcessResult is observed.  

Timeout and interruption stop only this external observation. They never cancel
the target or alter a Process wait edge. The implementation must shield the
Kernel completion future from handler-task cancellation. Timeout is REJECTED
with `gateway.timeout` and `retryable=true`; client interruption is INTERRUPTED.

The reply gate serializes result, timeout, interrupt, and close. If the completion
future and timeout are both observable when the gateway evaluates the deadline,
the completed ProcessResult wins. Otherwise the first committed terminal reply
wins.

This operation may observe any Process permitted by policy. It is distinct from
the child-only `Wait` Action, which registers a Process synchronization edge.

### 9.6 CancelProcess

Input: target PID, `self` or `tree` mode, and reason.  
Success point: the public Kernel cancel operation returns the target's terminal
ProcessResult under the current 0.1 API. The irreversible lifecycle linearization
point may occur earlier, when the Kernel first commits CANCELLING. The gateway
does not expose that earlier point as a successful reply in protocol 0.1.

Before dispatch, interruption prevents the cancel call. After dispatch, the
shielded cancel call continues: interruption stops observation but does not
reverse an accepted cancel decision. The target continues toward its unique
terminal result. Repeating cancel in a later request follows Kernel cancellation
idempotency rules.

### 9.7 InspectProcess and InspectTree

Input: one PID.  
Success point: immutable snapshot data is created.  
The reply never exposes mutable Process Table or mailbox objects.

### 9.8 ReapProcess

Input: one PID.  
Success/linearization point: the Kernel atomically removes the completed Process
from its live table and returns its immutable ProcessResult.  

Interruption before dispatch prevents reaping. After dispatch, the shielded reap
may commit even if interruption wins the reply gate. Interruption after commit
cannot restore the Process. Retrying an uncertain reap may return
`kernel.process_not_found`; this is not proof that the original request failed.

## 10. Action parity without boundary collapse

External requests and in-process Actions may describe similar operations, but
their continuation mechanisms differ:

| Operation | External completion | In-process completion |
| --- | --- | --- |
| spawn | ControlReply with PID | `Spawned` or `ChildrenCompleted` Event |
| unregister image | ControlReply with removed descriptor | trusted host operation only |
| send | unavailable until external-ingress semantics exist | next Event after `Send` Action |
| wait | external ProcessResult observation | `ChildrenCompleted` Event and wait edge |
| cancel | ControlReply / interrupted observation | `OperationCompleted` or caller cancellation |
| inspect | ControlReply snapshot | future explicit Kernel Action if required |

The Kernel must not branch on HumanShell, RuleShell, LLMShell, Tool, or Agent
identity. Equality means all running software follows Event/Action activation
semantics. It does not mean an external socket connection is secretly a Process.

## 11. Concurrency and backpressure

- Requests in different sessions may run concurrently.
- Requests in one session may also run concurrently unless an adapter deliberately
  provides a sequential client policy.
- Reply order is unconstrained and correlated only by RequestId.
- Each session and the gateway as a whole have positive in-flight limits.
- Exact limit and deadline values are deployment configuration, exposed through
  session diagnostics, rather than protocol constants.
- Capacity rejection occurs before handler dispatch and has no Kernel side effect.
- One slow `WaitProcess` must not block unrelated request dispatch.
- Control concurrency cannot bypass the Kernel's own activation or process limits.

## 12. Versioning and feature negotiation

The first protocol version is `0.1`. A session negotiates exactly one supported
version before accepting requests. Unknown operations and unsupported optional
features are stable REJECTED replies after request admission.

Within `0.1`, fields may be added only when receivers are required to ignore
unknown fields. Removing a field, changing its meaning, or changing an operation
success point requires a new protocol version.

Transport-specific features, including FUSE writable nodes, cannot silently
change base operation semantics.

## 13. Required invariants

1. `(SessionId, RequestId)` names at most one admitted request.
2. Every admitted request commits exactly one terminal ControlReply.
3. No request commits both a normal reply and INTERRUPTED.
4. Reply delivery failure never rolls back a committed Kernel effect.
5. Request interruption never means Process cancellation.
6. Session close never means Process cancellation or Kernel shutdown.
7. An interrupted WaitProcess never cancels its target or completion future.
8. A committed SpawnProcesses operation always leaves admitted Processes, even if
   their PID reply cannot be delivered.
9. An external session cannot claim a source PID or create an attached child on
   behalf of an existing Process.
10. Session-supplied metadata cannot increase Principal or Authority.
11. Gateway code never accesses mutable Process Kernel internals.
12. Transport adapters cannot redefine operation success points.

## 14. Conformance test table

| Area | Required cases |
| --- | --- |
| admission | malformed frame, unsupported version, reused ID, capacity rejection |
| reply gate | success/interrupt race, rejection/interrupt race, duplicate completion |
| interruption | before dispatch, during wait, after Kernel commit, repeated interrupt |
| disconnect | no in-flight work, active wait, committed spawn, drain timeout |
| spawn | authority ceiling, parent policy, pre-commit interrupt, post-commit lost reply |
| wait | result, timeout, interrupt, target continues, shielded completion future |
| cancel | terminal target, failing target, interrupt after cancellation acceptance |
| inspect | immutable result, reaped target, concurrent process transition |
| reap | active rejection, successful commit, uncertain retry after lost reply |
| catalog | factory-free list/resolve, ambiguity, selected provider, in-use unregister |
| authority | forged context fields, visibility without mutation rights, audit contents |
| concurrency | out-of-order replies, per-session limit, global limit, session isolation |
| layering | gateway uses only public Kernel API, adapter-neutral error mapping |

## 15. Deferred questions

- Cross-session idempotency keys and durable outcome recovery.
- Reply replay after reconnect.
- Streaming replies and flow-controlled output.
- Subscription/watch requests and notification invalidation.
- Durable session identity.
- Transactional multi-operation requests.
- A stable public operation for adopting or spawning under an existing Process.
- External input delivery without forging a Process message source PID.
- Exact permission vocabulary and scope matching, pending the authority milestone.
- Whether successful cancellation should reply at decision commitment instead of
  terminal cleanup in a later protocol version.
