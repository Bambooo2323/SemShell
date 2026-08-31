# Host Boundary and Sandbox Model

## 1. Decision

SemShell is a lightweight semantic virtual machine hosted by an existing
operating system. Its Processes, lifecycle, IPC, principals, authorities, and
capabilities form the guest execution model. Host files, networks, terminals,
secrets, clocks, and subprocess facilities remain outside that model and must
enter through explicit resource bridges.

An external connection is not a second kind of Operator. HumanShell,
RuleShell, LLMShell, tools, services, and ordinary programs are all guest
Processes and use the same Event/Action ABI. Host-facing code exists only to
boot the runtime, attach devices and resources, and administer or debug the
virtual machine.

```text
Host OS
├── runtime bootstrap
├── console and resource bridges
└── host administration/debugging
            │
            ▼
SemShell Kernel
├── Process Table and lifecycle
├── Event/Action scheduling and IPC
├── Principal and Authority
└── resource bindings
            │
            ▼
Guest Processes
├── HumanShell / RuleShell / LLMShell
├── workspace and network services
├── tools and coordinators
└── ordinary programs
```

## 2. Operators and bridges

An Operator makes execution decisions and therefore must be a Process. A
bridge does not make semantic decisions on behalf of an Operator; it exposes a
specific Host resource to authorized guest software.

| Entity | Process | Responsibility |
| --- | --- | --- |
| HumanShell, RuleShell, LLMShell | yes | Interpret goals or input and return Actions |
| WorkspaceService, NetworkService | yes | Provide guest-visible resource protocols |
| Tool, coordinator, memory service | yes | Ordinary guest software |
| Terminal connection | no | Carry console input and output |
| Host directory mapping | no | Bind a guest path to a selected Host directory |
| Host network implementation | no | Perform permitted Host network operations |
| Runtime bootstrap | no | Create the Kernel and initial Processes |
| Host administration interface | no | Debug, diagnose, stop, or configure the VM |

The normal CLI path is therefore:

```text
Host terminal
    -> console bridge
    -> HumanShell Process Event
    -> HumanShell Action
    -> Kernel
```

The console bridge is bound to a particular console-owning Process. It is not
a generic facility for injecting messages into arbitrary PIDs. Process IPC
continues to derive its source PID from the running Process context.

## 3. Resource bridge model

A bridge defines which part of a Host resource is visible in the guest and
translates between guest and Host representations. Even a pass-through bridge
is a mediation point because it selects exposure, maps identity, normalizes
errors, and provides an audit location.

For a workspace mapping:

```text
Guest path                         Host path
/workspace/src/main.py     ->      D:\Projects\Demo\src\main.py
```

Guest software should not receive the unrestricted Host path. A typical access
flow is:

```text
FileEditor Process
    -> structured IPC
WorkspaceService Process
    -> validated bridge request
Workspace bridge
    -> Host filesystem operation
```

Network, secrets, clocks, subprocess execution, and other external resources
follow the same shape. The Kernel remains role-neutral: it manages identity,
authority, lifecycle, IPC, and unforgeable resource bindings, while guest
services define resource-specific protocols and bridges perform Host calls.

## 4. Relationship to sandboxing

This architecture is the foundation of a sandbox, but resource bridges alone
are not a complete sandbox.

A sandbox requires both:

1. **Mediation**: permitted Host access has an explicit bridge where scope,
   identity, policy, and audit can be applied.
2. **Containment**: guest code cannot bypass that bridge and call unrestricted
   Host APIs directly.

The current in-process Python prototype provides semantic mediation but not
strong containment. A trusted `ProcessProgram` can still import `os`, open Host
files, or create sockets directly because every program runs in the same Python
interpreter. Authority currently describes admission and intended access; it
does not by itself enforce an operating-system security boundary.

The current system should therefore be described as:

```text
semantic VM with a soft resource sandbox
```

It must not yet be described as a security sandbox for untrusted Python code.

Strong sandbox enforcement can later place Process execution behind an actual
isolation boundary, such as a restricted subprocess, container, WASM runtime,
separate worker daemon, or platform security mechanism. That change should not
alter the Process/Event/Action contract or the guest resource protocols.

## 5. Control boundary

The ControlGateway should be treated as a Host/VMM administration and testing
interface, not as the normal syscall path for Human, LLM, or scripted
Operators. Appropriate Host control operations include boot, shutdown,
trusted image loading, bridge configuration, console attachment, diagnostics,
emergency cancellation, and test observation.

Normal guest behavior remains:

```text
Process -> Action -> Kernel -> Event
```

Host administration remains explicitly separate:

```text
Host administrator -> Host control interface -> runtime
```

Keeping these boundaries separate prevents an external session without a PID,
mailbox, owner, or Process lifetime from becoming a more privileged execution
entity than guest software.

## 6. Required invariants

1. Every semantic Operator is an admitted Process.
2. HumanShell, RuleShell, and LLMShell use the same Event/Action ABI.
3. External connections cannot claim or manufacture a Process source PID.
4. A console bridge can deliver input only to its bound console Process.
5. Host resources are exposed through explicit, scoped bindings.
6. Guest services are replaceable Processes; Host bridges belong to the trusted
   runtime boundary.
7. The Kernel does not branch on Human, LLM, tool, memory, or coordinator roles.
8. Authority is not advertised as strong isolation until code execution cannot
   bypass resource bridges.
9. Adding stronger containment must preserve guest Process and resource
   protocol semantics.

## 7. Consequence for milestone 7

The CLI should attach to or bootstrap a HumanShell Process. CLI commands become
input to that Process, which produces the same structured Actions as RuleShell
and LLMShell. JSON Lines may encode console/device traffic or Host
administration, but it must not create a parallel privileged Operator model.

The current generic external-client wording should be revised before milestone
7 implementation continues. Generic external input to arbitrary Processes
should be replaced by a console binding, and ordinary CLI operations should be
implemented through Process Actions.
