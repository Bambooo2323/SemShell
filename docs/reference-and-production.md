# Reference Design and Production Runtime

## 1. Repository decision

This Python repository is the executable reference design for SemShell. It is
not the first implementation layer of a future production scheduler.

Its job is to make four architectural claims observable and testable:

1. LLM-backed software, deterministic tools, coordinators, and human-facing
   shells can be represented as equal Processes.
2. Process behavior can use one explicit Event/Action contract instead of an
   Agent-owned hierarchy of tools and subagents.
3. Host administration, guest execution, model providers, and Host resources
   can remain separate boundaries.
4. Identity, authority, ownership, waiting, cancellation, and results can be
   explained without relying on a specific container engine.

The Python ProcessKernel is a reference state machine, deterministic simulator,
executable specification, and conformance oracle. It should not grow into a
reimplementation of Linux process management.

## 2. Two products, not two layers of one codebase

```text
SemShell design repository                 SemShell runtime repository

executable semantics                       production control plane
deterministic in-process model              Linux/OCI process execution
architecture demonstrations                durable operational state
offline conformance tests                  authenticated APIs and transports
soft Host-resource proof                   enforced isolation and policy
article and design support                 deployment and observability
```

The production runtime should be a separate repository. It may reuse protocol
schemas and conformance cases, but it should not import ProcessKernel as its
execution engine or gradually replace its internals with Docker calls.

This prevents the reference model from accumulating compatibility layers,
deployment configuration, daemon state, and platform-specific failure handling
that obscure the design argument.

## 3. Responsibility split

### 3.1 Linux and the container runtime own mechanism

The application implementation delegates these responsibilities to the
existing platform:

- CPU scheduling and real process execution;
- signals and process termination;
- PID namespaces and process visibility;
- mount, network, IPC, UTS, user, and cgroup namespaces;
- filesystem construction and executable startup;
- cgroup CPU, memory, I/O, PID, and device limits;
- Linux capabilities, `no_new_privileges`, seccomp, and LSM enforcement;
- container creation, start, state observation, kill, and deletion.

OCI defines container bundles, process configuration, namespaces, cgroups, and
runtime lifecycle. Docker is one convenient engine/API above those mechanisms;
it is not part of the SemShell semantic model.

References:

- [OCI Runtime Specification](https://github.com/opencontainers/runtime-spec)
- [OCI Linux configuration](https://github.com/opencontainers/runtime-spec/blob/main/config-linux.md)
- [OCI runtime lifecycle](https://github.com/opencontainers/runtime-spec/blob/main/runtime.md)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)

### 3.2 SemShell still owns meaning

Linux and Docker do not define:

- semantic ProcessImage metadata and capabilities;
- logical Process identity and ownership relationships;
- Principal and requested/effective Authority;
- exact operation-policy and authority decisions;
- structured Event, Action, Message, and ProcessResult contracts;
- Operator replacement between Human, Rule, and LLM implementations;
- resource-binding identities and semantic permission mapping;
- audit records explaining semantic decisions;
- application-level wait, coordination, and result composition.

The production SemShell control plane translates these semantic values into
container-runtime configuration and interprets runtime events back into
semantic results. It does not replace the Linux kernel.

## 4. Initial production mapping

The first production implementation should use one container execution for one
SemShell Process. This is intentionally coarse but keeps identity, cancellation,
resource limits, and cleanup understandable.

| Reference concept | Production representation |
| --- | --- |
| ProcessImage | immutable OCI image digest plus signed SemShell semantic manifest |
| ProcessSpec | validated execution request compiled into container configuration |
| SemShell PID | control-plane logical ID, distinct from host PID and container ID |
| ProcessControlBlock | durable control-plane record plus observed runtime state |
| ProcessProgram | container entrypoint implementing the worker contract |
| Started Event | first control-plane Event after authenticated worker registration |
| ProcessAction | structured worker-to-control-plane request |
| ProcessEvent | structured control-plane-to-worker delivery |
| Spawn | validate policy, then create and start another container |
| Message | bounded broker/control-plane delivery, not a Linux signal |
| Wait | control-plane dependency over logical Process results |
| Cancel | lifecycle decision mapped to graceful stop and forced termination |
| ProcessResult | semantic result plus exit status and bounded diagnostics |
| Authority | policy compiled into mounts, network, secrets, identity, and limits |
| ResourceBinding | mount, Unix socket, proxy, secret, device, or scoped endpoint |
| Catalog | semantic manifest index associated with immutable OCI digests |
| ControlGateway | authenticated production API/control-plane service |
| audit tuples | durable append-only operational records |

Logical SemShell PID must remain distinct from Linux PID, namespace PID, Docker
container ID, and runtime task ID. Platform identifiers are observations
attached to a logical Process and may differ across backends.

## 5. Production topology

```text
Human / LLM Operator / automation
                |
        authenticated API
                |
      SemShell control plane
       /        |          \
 policy     state/audit    worker channel
 engine       store             |
                                  v
                     container engine / OCI runtime
                                  |
                             Linux kernel
                                  |
                     isolated Process execution
```

The control plane owns semantic admission and orchestration. The container
engine owns execution lifecycle. The worker channel carries SemShell
Event/Action frames. The state store records logical identity and results.

More precisely, the control plane owns desired semantic state, authorizes and
issues lifecycle operations, commits logical transitions, and publishes the
exactly-one ProcessResult. The engine performs create/start/stop/kill/delete and
reports runtime observations. An engine observation never commits a semantic
result by itself.

The Docker daemon or container-runtime socket must never be mounted into a
guest Process container. That would let guest software bypass SemShell
admission and control arbitrary containers.

## 6. Worker protocol boundary

The reference `ProcessProgram.handle()` call becomes a cross-process protocol:

```text
control plane -> Event envelope -> worker shim/program
control plane <- Action envelope <- worker shim/program
```

The first implementation should use a dedicated authenticated Unix socket or
equivalent runtime channel mounted only into that container. It should not infer
Actions from arbitrary stdout. Stdout and stderr remain bounded diagnostic
streams; the worker channel remains the source of semantic truth.

Before any Started Event, the worker sends a distinct WorkerRegistration frame
containing its one-time execution identity and protocol version. Registration
is not an Event and cannot contain a ProcessAction. The control plane validates
it against the logical PID, execution ID, container identity, and bootstrap
credential before sending the first Event.

Each execution receives a short-lived bootstrap credential bound to one
logical Process ID and container execution. The worker cannot claim another
PID, Principal, Authority, or parent relationship. Reconnection, replay, and
leases should wait until the first non-durable worker contract is stable.

## 7. Lifecycle mapping

```text
semantic admission
  -> create container
  -> persist logical/runtime identity mapping
  -> start container
  -> accept authenticated worker registration
  -> exchange Event/Action frames
  -> observe structured result and runtime exit
  -> commit one ProcessResult
  -> retain or delete container according to diagnostics policy
```

Cancellation is a semantic decision before it is a signal:

1. atomically commit the Process as cancelling;
2. stop accepting new semantic Actions from that execution;
3. request graceful container termination;
4. wait for a configured grace period;
5. force termination if the workload does not exit;
6. commit one cancelled ProcessResult;
7. suppress late worker messages.

The logical terminal transition uses one compare-and-set decision record.
Normal result, abnormal runtime exit, cancellation, channel loss, and control-
plane reconciliation compete to commit that record; only the winner publishes
ProcessResult. Later observations become audit/diagnostic data and cannot
replace the result.

Docker documents graceful stop as the configured stop signal—SIGTERM by
default—followed by SIGKILL after the timeout. This mechanism fits the mapping
but does not define the SemShell cancellation winner or result semantics.

Reference: [Docker container stop](https://docs.docker.com/reference/cli/docker/container/stop/).

### 7.1 Initial execution and ownership rules

Production v1 has exactly one container execution attempt per logical Process.
It performs no automatic recreate or restart. A user-visible retry creates a
new logical PID. Attempt identity may be recorded for audit but does not create
multiple attempts under one Process in v1.

The container, its PID namespace, and all OS descendants inside it together
form one SemShell Process. A child process created with SemShell Spawn is a new
logical Process and a new container execution. Unreported `fork`/subprocess
descendants remain internal implementation details of their owning container.
Cancel targets the entire container/cgroup, not one observed Linux PID.

Ownership follows the reference semantics: every SemShell-spawned child is
attached, cancellation covers the selected Process and all attached
descendants, and a parent cannot commit normal success while children remain
active. Independent logical roots are created only by trusted bootstrap without
a parent PID. Principal identity, parent/owner PID, and the human/service that
submitted an external request are distinct recorded fields.

### 7.2 Worker and control-plane failure rule

Before replay and reconnect exist, worker-channel loss is fail-closed. The
control plane stops the container and attempts to commit a failed ProcessResult
with stable code `worker_channel_lost`, unless another terminal decision already
won. After control-plane restart, reconciliation stops executions whose durable
logical/runtime identity and state record cannot be reconstructed and commits
or retains an explicit unknown/failed recovery record; it never silently adopts
them.

## 8. Authority compilation

Semantic Authority should not be renamed Docker configuration. It is policy
input compiled into an execution profile.

The trusted control plane assigns Principal from authenticated admission,
validates requested Authority, computes effective Authority, and invokes a
versioned execution-profile compiler. The worker and container image cannot
select their own effective Authority. Admission fails if compilation is
ambiguous or the selected backend cannot enforce every required profile field.
Audit records bind requested Authority, effective Authority, compiler/profile
version, emitted runtime configuration digest, and observed enforcement result.

```text
Permission("workspace.read", "project-a")
  -> resolve trusted Host binding project-a
  -> read-only bind mount at a fixed guest path
  -> record binding identity and mount result

no network Permission
  -> container network mode: none

memory/cpu budget
  -> explicit cgroup-backed runtime limits

model.invoke Permission
  -> scoped model proxy/socket and short-lived credential
  -> no unrestricted Host credential by default
```

Docker bind mounts are writable by default, so read-only intent must be
explicit. Docker also applies no CPU or memory constraints by default, so every
production profile must choose limits rather than assume containment. Network
denial should be explicit; Docker's `none` driver provides loopback only.

The minimum hostile-workload profile is fail-closed and includes: no privileged
mode; non-root execution with a trusted user/user-namespace policy; dropped
Linux capabilities unless explicitly granted; `no_new_privileges`; a trusted
seccomp and LSM profile where supported; isolated PID, mount, IPC, UTS, network,
and cgroup namespaces; controlled devices; read-only root filesystem; bounded
writable tmpfs; and explicit memory, CPU, PID, wall-time, output/log, disk, swap,
and OOM behavior. If the platform cannot enforce the selected profile,
admission fails.

Read-only bind mounts are not sufficient by themselves. Trusted binding
resolution must define canonical source paths, symlink handling, mount
propagation, recursive submount behavior, guest destination, and cleanup. A
granted network permission uses a scoped proxy or enforceable egress policy;
ordinary container networking cannot express semantic destination/action
permissions.

The trusted manifest pins the graceful termination signal instead of accepting
guest-controlled image metadata. After termination the runtime revokes
short-lived credentials, exports bounded sanitized diagnostics, and deletes the
container and writable layer by default. Retention requires a separate trusted
policy and must not retain secrets implicitly.

The worker socket exposes one per-execution endpoint only. Frame size, message
rate, queue capacity, authentication replay, credential revocation, and socket
cleanup are bounded and owned by the control plane. OCI containers are not
claimed as sufficient isolation for every hostile multi-tenant threat model;
deployments requiring a stronger boundary must select a VM-backed or equivalent
isolation profile.

References:

- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [Docker none network](https://docs.docker.com/engine/network/drivers/none/)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)

## 9. What does not move into production unchanged

These Python implementations express semantics but are not production
components:

- the asyncio Process scheduler;
- in-memory PID allocation and Process Table;
- Python ProcessControlBlock objects;
- direct in-process ProcessProgram calls;
- in-memory mailboxes and completion futures;
- InMemoryResourceBridge and trusted-tree LocalWorkspaceBridge;
- the local demonstration ControlSession and REPL runtime;
- in-memory audit lists;
- fake delayed tasks proving cancellation races.

Their invariants and conformance tests matter. Their mechanisms do not.

## 10. What should be shared

Sharing happens through small versioned artifacts, not imports from the
reference Kernel:

- protocol schemas for Event, Action, ProcessResult, and worker registration;
- semantic image-manifest schema;
- stable error and lifecycle vocabulary;
- permission and resource-binding vocabulary;
- language-neutral conformance fixtures and transition tables;
- example transcripts showing equivalent Human, Rule, and LLM behavior.

The design repository is the canonical source for released schema and fixture
versions. Production repositories consume immutable published artifacts or
copied generated bindings tied to a release digest; they never import the
Python reference package as a runtime dependency.

The production repository may be written in Python, Go, or another language.
Language choice is secondary because the shared contract is data and behavior,
not Python inheritance.

## 11. Simplifying this design repository

Decision: preserve the complete reference in recoverable Git history, then
migrate the active branch into a focused design edition. The design edition is
an incompatible presentation-oriented revision whose active code demonstrates
the architectural argument with a smaller public contract.

Until the staged migration changes a boundary, the current implementation and
`docs/semantics.md` remain authoritative. The proposal and dependency-safe
sequence are maintained in
[`../devdoc/design_edition_simplification_plan.md`](../devdoc/design_edition_simplification_plan.md)
and
[`../devdoc/design_edition_migration_stages.md`](../devdoc/design_edition_migration_stages.md).

### Keep as the primary proof

- Kernel Process/Event/Action/lifecycle model;
- ProcessImage, ProcessSpec, Capability Catalog, Principal, and Authority;
- HumanShell, RuleShell, LLMShell, and the scripted backend;
- echo/coordinator architecture demonstration;
- core lifecycle, authority, Operator-equivalence, and architecture tests;
- concise public design, semantics, security, and codebase documentation.

### Reduce to focused boundary proofs

- generic ResourceBinding with an in-memory authorization demonstration;
- a small trusted Host administration facade with no Process PID;
- Console input and Process IPC as distinct identity paths.

The complete transport-neutral Control protocol, administration REPL, and local
filesystem bridge remain active until their migration stage. They receive no new
features and leave the active package only after their retained evidence has
moved to the focused boundaries above.

### Remove from this repository's roadmap

- production JSON Lines/socket/HTTP transports;
- persistence, journal, replay, checkpoint, and resume;
- subprocess/container executors and cgroup/signal management;
- supervisors, restart policy, and multi-worker leases;
- Docker profiles and deployment orchestration;
- production telemetry and remote package management;
- frontend streams, reconnect, and durable subscriptions.

Those are production-runtime concerns for the separate repository.

### Physical migration rule

Before removing active files, preserve the reviewed complete tree in a branch
and tag. Then migrate consumers, tests, exports, and current documentation before
deleting the Control package and local filesystem proof. Historical code remains
available through Git rather than an importable `archive/` package. Do not
combine files merely to reduce file count: useful package boundaries communicate
the architecture.

## 12. Separate production-runtime milestone

After the design edition is frozen, production work belongs in the separate
runtime repository. Its specification should produce:

1. versioned, language-neutral schemas for registration, Event, Action, and
   ProcessResult frames;
2. explicit fields and invariants for logical Process, execution, container,
   and operating-system identities;
3. transition tables for the compare-and-set terminal decision, cancellation,
   late messages, channel loss, and restart reconciliation;
4. versioned Authority-to-execution-profile compiler inputs, outputs, failure
   rules, and audit fields;
5. trusted resource-injection and credential-lifetime profiles;
6. language-neutral conformance fixtures shared by both repositories.

Two semantic choices remain genuinely open and must be decided in that
specification: the admission/create/persist/start crash-recovery ordering, and
the precedence between a structured worker result and a conflicting runtime
exit status.

Only after the contract is versioned and those two choices close should the
separate application repository choose Docker Engine, containerd, or another
OCI-compatible implementation.
