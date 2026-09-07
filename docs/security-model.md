# SemShell Security Model

## Current boundary

Version 0.1 provides structured identity, authority admission, image execute
ACLs, and auditable decisions. It does not provide strong isolation for
untrusted Python programs.

All current ProcessPrograms execute in one Python interpreter. Trusted program
code can import Host modules, open files, or create sockets directly. Authority
therefore describes SemShell admission and delegation rules, not an
operating-system sandbox.

The accurate description is:

```text
semantic VM with semantic policy mediation and no code containment
```

## Identity and authority

A Principal is a stable namespaced identity such as `human:alice` or
`service:ci`. Authority is an immutable set of exact capability/scope pairs.
Requested authority in a ProcessSpec is only a request.

Capability scopes use exact matching in version 0.1. For example,
`Permission("fs.write", "/workspace/src")` does not imply access to a parent
scope or automatically define wildcard/path traversal behavior. Resource
services must define any future hierarchical scope semantics explicitly.

Admission combines:

- caller or parent authority;
- image authority declaration and minimum requirements;
- system policy;
- a previously issued and policy-validated approval artifact.

Ordinary children cannot silently exceed parent authority. An unresolved
escalation produces an explicit approval-required result; the Kernel never
blocks inside spawn for an interactive decision.

Image execute ACL and Process effective authority are separate. Every admission
decision records the requester, image, requested and granted authority,
decision, reason, and approval identity when present.

Approval artifacts are exact policy-registered values in version 0.1. The Host
configuration that constructs the Policy is the root of trust. Artifacts have
no expiry, revocation, cryptographic signature, or single-use/replay semantics
in this prototype, so they must not cross an untrusted transport boundary.

## Host resources

Host terminals, workspaces, networks, secrets, and subprocess facilities should
be exposed through explicit resource bridges. A bridge provides mediation,
scope mapping, error normalization, and an audit point.

Mediation alone is not containment. Until Process execution is isolated, a
trusted in-process program can bypass a bridge and access APIs available to the
runtime interpreter.

The minimal resource proof implements this mediation boundary for read-only
workspace text. The Host fixes bindings at Kernel construction. The Kernel
derives invocation identity and caller context, enforces the binding-scoped
Permission before Host code runs, bounds concurrent bridge tasks, normalizes
public failures, and emits payload-free audit phases.

The local bridge accepts only a strict portable relative-path grammar, bounds
result bytes, resolves existing paths below its configured root, and performs
no writes. This blocks lexical traversal and pre-existing escaping links in a
trusted temporary tree. It is not a race-resistant filesystem sandbox:
concurrent adversarial link or junction mutation is explicitly outside the
proof.

## Control boundary

External Control sessions have no SemShell PID and cannot claim a Process
source PID or create ownership on behalf of an existing Process. Control is
reserved for Host administration and tests. Normal Human, Rule, and LLM
Operators are admitted Processes and use Event/Action semantics.

The console bridge is fixed to one selected Process when created. Console input
is distinct from PID-originated Process IPC.

Runtime bootstrap is trusted Host code. It selects the initial Catalog, Policy,
root Principal and Authority, Operator Process, and console binding. Version
0.1 does not define remote authentication or delegate this root-of-trust
configuration to guest software.

The local Control CLI derives its Principal and Authority from trusted
bootstrap configuration. Command text cannot replace that identity or enlarge
the session Authority. Its bootstrap grants the three administration
permissions required by its mutating commands: `control.process.cancel`,
`control.process.reap`, and `control.catalog.unregister`. Its encoder accepts
structured containers and scalar values, plus an explicit closed set of
SemShell dataclass and Enum types. It fails closed on arbitrary Host objects
instead of falling back to `repr()` or exception text.

## Production containment boundary

This reference repository intentionally does not add subprocess, container,
worker-daemon, or WASM executors. Enforced containment belongs to the separate
production runtime described in
[reference-and-production.md](reference-and-production.md).

The initial production mapping uses one isolated container execution per
logical SemShell Process. Any backend must preserve Process identity,
lifecycle, Event/Action, cancellation, Authority, and ProcessResult semantics;
execution profiles must not introduce role-specific branches for LLMs, tools,
memory, or coordinators.

## Explicit non-goals

Version 0.1 does not claim protection against:

- malicious ProcessImage factories or ProcessPrograms;
- Python interpreter compromise;
- denial of service by trusted in-process code;
- data sharing between programs in the same interpreter;
- Host API access outside SemShell Authority checks.
