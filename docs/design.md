# SemShell Design

SemShell is a small process-centric runtime for studying an LLM-operated CLI
environment. It is an executable architecture argument, not a complete
operating system or production Agent framework.

## Three claims

Version 0.1 is built to demonstrate three claims:

1. LLM-backed programs, deterministic tools, coordinators, memory services,
   and Operators can all be represented as ordinary Processes.
2. HumanShell, RuleShell, and LLMShell can use the same Event/Action ABI without
   role-specific Kernel behavior.
3. Software can be composed through image discovery, spawn, IPC, wait, and
   results instead of an application-owned Agent/tool object hierarchy.

## Flattened execution model

```text
Traditional Agent application       SemShell

Agent                               Kernel
├── tools                           ├── Process
├── memory                          ├── Process
├── subagents                       ├── Process
└── orchestration loop              └── Process
```

Some SemShell Processes use an LLM. Some are deterministic tools. Some act as
coordinators or shells. These are software roles, not Kernel entity types.

The Kernel recognizes only generic execution concepts:

- ProcessImage and ProcessSpec;
- Process identity, ownership, lifecycle, and results;
- structured Event, Action, and IPC messages;
- Capability Catalog discovery;
- Principal and Authority.

The next proof adds generic Host resource bindings without teaching the Kernel
about filesystems. A Process returns `InvokeResource(binding_id, operation,
input)`; the Kernel authenticates the caller, checks the binding's trusted
operation-to-Permission map, and delegates to a passive bridge. The unchanged
workspace-reader guest works with both an in-memory bridge and a local
read-only bridge.

## Image, specification, and execution

```text
ProcessImage + ProcessSpec -> Kernel admission -> Process
```

A `ProcessImage` is an immutable versioned software definition. A
`ProcessSpec` is one request to run an image or resolved capability with input,
ownership, and requested authority. A `Process` is the admitted runtime
instance with a PID, mailbox, lifecycle, and final result.

Images are registered through the Capability Catalog. Resolving a capability
selects software; it does not execute it. Ambiguous provider selection is
rejected unless the caller names an exact provider.

Processes receive factory-free Catalog descriptors: metadata such as image
identity, capabilities, schemas, and authority declarations, without the Host
callable that constructs the program. Discovery therefore cannot execute or
replace software.

## Event/Action ABI

Every running program implements the same activation contract:

```python
async def handle(context: ProcessContext, event: ProcessEvent) -> ProcessAction:
    ...
```

The Kernel delivers one event, the ProcessProgram returns one action, and the
activation ends. The same Process is never activated concurrently.

Multi-step behavior is retained in program-private state and progresses through
later Events. For example, Spawn produces a later `ChildrenCompleted` Event;
the next handler activation can then return Exit.

Actions include spawn, send, wait, cancel, detach, discovery, resource
invocation, yield, exit, and fail. Continuations arrive as Events. This makes scheduling, ownership,
cancellation, and audit behavior explicit rather than hiding them inside an
Agent loop.

## Equal Operators

HumanShell, RuleShell, and LLMShell are ordinary ProcessPrograms. In the
version 0.1 demonstration they all:

1. receive the same `OperatorTask`;
2. request factory-free Catalog metadata;
3. choose an ordinary Spawn Action;
4. wait for the same coordinator Process;
5. return the same terminal value.

LLMShell uses a provider-neutral `SemanticBackend`. The offline demonstration
uses a scripted backend that returns a structured Action. Model SDK types never
enter the Kernel.

## Minimal demonstration

```text
Operator Process
└── coordinator
    ├── echo("alpha")
    └── echo("beta")
```

The coordinator performs fan-out/fan-in with ordinary Spawn and Wait Actions.
The Kernel has no built-in coordinator operation.

Tree equivalence in this demonstration means the same ownership shape and the
same coordinator/worker images and terminal values. The root Operator image is
expected to differ.

## Host and guest boundary

SemShell is a semantic virtual machine hosted by Python and an existing OS.
Operators and application software are guest Processes. Terminals, Host files,
networks, and runtime administration are Host resources or bridges.

The ControlGateway is a Host administration and testing boundary, not a second
privileged Operator model. A console bridge may be bound to a HumanShell PID;
it cannot manufacture Process IPC provenance or act as an arbitrary source PID.

The version 0.1 demo CLI follows this exact path:

```text
Host CLI
    -> create Kernel and register demo images
    -> spawn the selected Operator root with OperatorTask as ProcessSpec input
    -> wait for and print the root ProcessResult and tree
```

The CLI does not make the Operator decision and does not route the demo through
ControlGateway. A future interactive frontend may attach a console bridge to an
already admitted HumanShell and deliver subsequent `ConsoleInput` Events.

Resource bindings are fixed when a Kernel is constructed. Binding IDs are
opaque identities and exact Authority scopes; guests cannot discover Host
paths or supply their own PID, Principal, Authority, or invocation ID. Bridge
results return through ordinary continuation Events, while cancellation
permanently suppresses late delivery.

## Non-goals for version 0.1

- production CLI completeness;
- general remote clients or frontend streaming;
- strong sandboxing of untrusted Python code;
- persistent or distributed Processes;
- a filesystem, network stack, or container scheduler;
- performance comparison with existing Agent frameworks.

The project is primarily about engineering structure, explainability, and
software management rather than execution speed.
