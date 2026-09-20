# Version 0.1 Scope: Architecture Proof

> Historical design context. Current guarantees are defined in
> [docs/semantics.md](../docs/semantics.md), with final evidence in the
> [design-edition validation record](../docs/design-edition-validation.md).
> The pre-removal Stage 3 implementation is recoverable from Git tag
> `complete-reference-20260915`; older contracts remain in ancestor history.
> Proposals and completion criteria below do not add active API guarantees.

## 1. Release purpose

Version `0.1` is an executable architecture argument, not a complete CLI
operating environment. Its purpose is to make the flattened Process model
small enough to understand, run, and falsify.

The release must prove three claims:

1. LLM-backed software, deterministic tools, coordinators, and Operators are
   ordinary Processes under one Kernel model.
2. HumanShell, RuleShell, and LLMShell are replaceable implementations of the
   same Event/Action contract; the Kernel does not identify their roles.
3. Software composition is expressed through ProcessImage discovery, spawn,
   IPC, wait, and results rather than an application-owned Agent/tool graph.

Anything that does not strengthen one of these proofs is deferred by default.

## 2. Minimum executable surface

The minimum `0.1` runtime contains:

- the existing deterministic Process Kernel;
- the Capability Catalog and authority admission model;
- one shared Operator task envelope;
- HumanShell, RuleShell, and LLMShell ProcessImages;
- a scripted semantic backend for offline LLMShell execution;
- one deterministic worker image;
- one coordinator image that demonstrates explicit spawn/wait/aggregate;
- one command that runs the same task through each Operator;
- process tree, result, and authority-decision output sufficient to explain the
  execution.

The demonstration should be intentionally small. A suitable task is to resolve
a capability, spawn several deterministic workers, wait for them, and aggregate
their results. The three Operators may choose the same valid Action through
different implementations.

## 3. Boundary model for 0.1

Running guest software uses only the Process Event/Action ABI:

```text
Process Event -> ProcessProgram.handle() -> Process Action
```

The terminal adapter may bootstrap or attach to HumanShell and deliver input to
that bound console Process. It must not become a generic external Operator or
inject Process messages into arbitrary PIDs.

The existing Control protocol remains a Host administration and test boundary.
Version `0.1` does not need to turn it into a complete remote client platform.
JSON Lines, sockets, FUSE, long-lived streams, and general frontend connections
are deferred.

## 4. Minimum CLI

The CLI only needs to make the architecture proof runnable. A single shape is
sufficient:

```text
semshell demo --operator human|rule|llm
```

Optional diagnostic flags may print Process snapshots, the final tree, and
authority audit records. A complete interactive shell and a full set of
`images`, `ps`, `tree`, `spawn`, `send`, `wait`, `cancel`, `inspect`, and `reap`
commands are not release requirements.

The CLI is a Host terminal adapter. The semantic execution path begins at the
admitted Operator Process.

## 5. Minimum software set

Only two ordinary guest programs are required:

- `echo` or an equivalent deterministic worker, proving basic input/result
  behavior;
- `coordinator`, proving fan-out/fan-in through explicit Process operations.

Approval, memory, Python runner, test runner, file editor, network, and repair
software are valuable examples but do not add a new core architectural proof.
They belong after `0.1`.

## 6. Required tests

In addition to existing Kernel, cancellation, Catalog, Control, and authority
tests, `0.1` needs only:

- one shared Operator contract suite applied to all three Shell programs;
- an offline scripted LLMShell test;
- a role-neutrality test showing the Kernel does not import or branch on Shell,
  LLM, tool, memory, or coordinator types;
- one end-to-end parameterized demonstration test for Human, Rule, and fake LLM
  Operators;
- assertions that the resulting Process tree and terminal values are equivalent
  where the task semantics require equivalence.

## 7. Explicit non-goals

The following are not required for `0.1`:

- a production-quality interactive CLI;
- a general external Operator protocol;
- JSON Lines, socket, FUSE, SSE, or WebSocket adapters;
- streaming model output;
- real model or network access in tests;
- memory, approval, package-management, or repair workflows;
- Host security isolation or per-Process containers;
- persistence, replay, checkpointing, or remote workers;
- performance optimization.

## 8. Completion test

A reader unfamiliar with the implementation should be able to run three short
commands, compare their Process trees, and conclude that only the Operator
implementation changed. The same Kernel and ordinary ProcessImages must be used
in all three runs.

The release is complete when the code and documentation make the three claims
in Section 1 directly observable without requiring a large feature tour.
