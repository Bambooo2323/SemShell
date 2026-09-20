# Deferred Docker Sandbox Plan

> Historical design context. Current guarantees are defined in
> [docs/semantics.md](../docs/semantics.md), with final evidence in the
> [design-edition validation record](../docs/design-edition-validation.md).
> The pre-removal Stage 3 implementation is recoverable from Git tag
> `complete-reference-20260915`; older contracts remain in ancestor history.
> Proposals and completion criteria below do not add active API guarantees.

## 1. Status

This document records a post-`0.1` containment direction. It is not part of
milestone 7 and must not delay the Process, Operator, CLI, or end-to-end
contracts.

The first implementation should run one complete SemShell runtime inside one
restricted container. SemShell remains responsible for guest semantics;
Docker provides a coarse Host security boundary.

```text
Host OS
└── restricted Docker container
    └── SemShell semantic VM
        ├── Process Kernel
        ├── resource bridges
        └── semantic Processes
```

## 2. Responsibility split

Docker and SemShell solve different problems and neither replaces the other.

| Layer | Responsibility |
| --- | --- |
| Docker | Host filesystem, network, user, CPU, memory, and PID containment |
| Resource bridges | Explicit mapping and mediation of selected Host resources |
| SemShell Kernel | Process identity, lifecycle, IPC, authority, and scheduling |
| Guest services | Resource-specific protocols and application behavior |

The effective resource boundary is the intersection of all layers:

```text
effective access =
    container exposure
    ∩ bridge policy
    ∩ Process authority
```

Docker defines the maximum resources available to the entire SemShell VM.
SemShell Authority delegates smaller scopes to individual semantic Processes.

## 3. Initial container profile

The default development and demonstration profile should use:

- a non-root container user;
- a read-only root filesystem;
- one explicit workspace mount at `/workspace`;
- a temporary writable `/tmp`, preferably backed by `tmpfs`;
- bounded memory, CPU, and PID counts;
- no privileged mode;
- dropped Linux capabilities;
- no Docker daemon socket;
- no Host home-directory, SSH, or cloud-credential mounts;
- network disabled unless the demonstration explicitly requires it;
- secrets exposed individually and read-only when required.

The guest path must remain independent from the Host path:

```text
Host:   D:\Projects\Example
Guest:  /workspace
```

Guest software should not need to know the Host path used to create the mount.

## 4. Security boundary and limitations

One container provides containment between the SemShell VM and the Host. It
does not isolate semantic Processes from each other.

Processes running in the same Python interpreter may still share or interfere
with:

- mounted workspace files;
- environment variables and injected secrets;
- the container network namespace;
- interpreter-global state;
- CPU, memory, and event-loop availability;
- any Host API exposed inside the container.

The initial Docker profile therefore upgrades the project from a soft Host
resource model to coarse VM-level containment. It does not make an untrusted
`ProcessProgram` safe relative to other Processes in the same runtime.

## 5. Incremental execution isolation

After the single-container profile is stable, selected ProcessImages may use
stronger execution backends without changing Process/Event/Action semantics.

```text
ProcessImage
    -> execution profile
    -> executor backend
    -> Process result/events
```

Candidate profiles are:

| Profile | Intended use |
| --- | --- |
| `trusted_in_process` | Kernel-adjacent and reviewed built-in software |
| `restricted_subprocess` | Deterministic tools needing OS process isolation |
| `isolated_container` | Python runners and untrusted or high-risk software |
| `wasm` | Portable capability-oriented execution where practical |

Execution profiles describe containment requirements, not semantic roles. The
Kernel must not branch on whether an image is an LLM, tool, memory service, or
coordinator.

## 6. Resource bridge implications

Docker mechanisms can implement the outer part of several Host bridges:

| SemShell resource | Docker mechanism |
| --- | --- |
| workspace | bind mount or named volume |
| temporary files | `tmpfs` |
| network | isolated Docker network or no network |
| CPU and memory | container resource limits |
| process count | PID limit |
| Host identity | non-root container user |
| secrets | individual read-only secret mounts |
| console | container stdin, stdout, and TTY |

These mechanisms do not replace guest services. A WorkspaceService still
defines guest file operations and checks Process Authority; the container mount
only limits the maximum Host filesystem visible if guest code bypasses that
service.

## 7. Delivery phases

### Phase A: reproducible containerized runtime

- Add a minimal runtime image and locked-down default launch configuration.
- Mount only the demonstration workspace.
- Run the existing offline test suite inside the container.
- Document which Host resources remain reachable.

### Phase B: explicit bridge profiles

- Define workspace and network exposure as runtime configuration.
- Produce structured diagnostics for active Host resource bindings.
- Add tests proving unmounted Host paths and disabled networks are unavailable.

### Phase C: isolated Process executors

- Define a transport-neutral executor contract.
- Add bounded subprocess or worker-container execution.
- Preserve PID, lifecycle, cancellation, Event/Action, and ProcessResult
  semantics across the execution boundary.
- Add conformance tests shared by in-process and isolated executors.

## 8. Non-goals for `0.1`

- Running every Process in its own container.
- Treating Docker as the guest Process scheduler.
- Mounting the Docker socket into SemShell.
- Replacing SemShell Authority with container configuration.
- Claiming isolation between in-process ProcessPrograms.
- Supporting orchestration systems or remote multi-host execution.

## 9. Completion criteria

The first Docker sandbox milestone is complete when:

1. the same SemShell demonstration and tests run inside the container;
2. the runtime uses a non-root, non-privileged default profile;
3. only an explicitly selected workspace is writable;
4. network availability is an explicit configuration choice;
5. no Host home directory, credential directory, or Docker socket is exposed;
6. documentation states that isolation applies to the VM as a whole, not
   between in-process semantic Processes;
7. containerization requires no role-specific branch in the Kernel.
