# Design Edition Simplification Plan

> Historical design context. Current guarantees are defined in
> [docs/semantics.md](../docs/semantics.md), with final evidence in the
> [design-edition validation record](../docs/design-edition-validation.md).
> The pre-removal Stage 3 implementation is recoverable from Git tag
> `complete-reference-20260915`; older contracts remain in ancestor history.
> Proposals and completion criteria below do not add active API guarantees.

Date: 2026-09-10

Status: proposed implementation plan. This document does not change current
runtime behavior or authorize deletion, release creation, or API migration.

The dependency-safe execution sequence is defined in
[`design_edition_migration_stages.md`](design_edition_migration_stages.md).

## 1. Objective

Make SemShell small enough that a reader can follow its architectural argument
from a runnable example to the implementation without first studying a general
administration protocol.

The design edition demonstrates equal Process execution for LLM-backed software,
ordinary programs, and Operators. Software templates and process creation express
composition; the Kernel has no Agent, Tool, Planner, or Memory roles. The benefit
being demonstrated is explicit engineering structure and lifecycle management.

Linux/OCI application implementation remains a separate project. This plan adds
no execution backend, deployment system, or production protocol.

## 2. Current evidence and adopted decision change

The inspected source contains approximately 1,400 lines in
`semshell/kernel/kernel.py`, 870 in `semshell/control/`, and 590 in
`semshell/cli/`. These counts include comments and blank lines; they indicate
reading surface, not code quality or a deletion target.

Stage 0 adopted the following scope changes. The table records the decisions
that preceded this plan and how the current planning documents supersede them:

| Source | Previous decision | Adopted planning change |
| --- | --- | --- |
| `docs/reference-and-production.md`, section 11 | Publish the complete reference; physical pruning is not selected | Preserve a recoverable complete baseline, then publish a focused design edition |
| `devdoc/TODO.md`, section 13 | Freeze physical pruning | Replace that freeze with the explicit file-level migration below |
| `devdoc/TODO.md`, section 14 | Complete cascade cancellation, pause/resume, and expanded Control interruption | Retain cascade cancellation; remove pause/resume and Control expansion from this edition's completion criteria |
| `devdoc/lifecycle_rearchitecture.md`, phases 1 and 2 | Completed internal lifecycle correctness work | Preserve its useful invariants and mechanisms; do not revert bug fixes to reduce line count |
| `devdoc/lifecycle_rearchitecture.md`, phase 3 | Public lifecycle and Control migration | Adopt only the reduced contract specified here |
| `devdoc/TODO.md`, sections 15 and 17 | Final demonstration and article depend on lifecycle closure | Depend on the reduced demonstrations and validation in this plan |

The planning documents are now synchronized, but no runtime migration has
started. Until a migration stage changes a boundary, `docs/semantics.md` remains
the current behavioral contract. This plan is not a claim that planned removals
have happened. The preserved baseline must capture the actual current
implementation, including later lifecycle work, rather than assuming that the
old version 0.3 label identifies every current change.

## 3. Design rules

1. Keep a feature in the core only when an included demonstration or a retained
   semantic invariant requires it.
2. Reduce supported behavior before simplifying its implementation. Moving an
   unchanged protocol into `examples/` does not remove its maintenance cost.
3. Preserve identity, admission, unique terminal results, cleanup ownership, and
   late-event suppression wherever asynchronous execution remains supported.
4. Keep useful module boundaries. Fewer files alone do not make the model easier
   to understand.
5. State removed capabilities explicitly. A smaller implementation must not keep
   claiming conformance to the complete historical protocol.

## 4. Minimum executable contract

| Concept | Design-edition contract |
| --- | --- |
| ProcessImage / ProcessSpec | Immutable executable definition and one admission request; keep exact image identity and capabilities |
| Catalog | Bootstrap registration and exact/unambiguous resolution; no live unregister workflow |
| Process | Unique logical PID, Principal, effective Authority, mailbox, ownership, terminal result |
| Activation | One Event in, one Action out; at most one active handler per Process |
| Spawn | Create attached children and return their PIDs; composition remains a runtime operation |
| Send | One structured payload with Kernel-derived source PID; omit MessageKind and correlation fields in this edition |
| Wait | Explicit wait-all over direct children, including empty and already-complete waits |
| InvokeResource | Explicit binding and operation; authenticate caller and check exact Permission before invoking Host code |
| Yield | End an activation and wait for input, or request an explicit continuation |
| Exit / Fail | Commit one structured terminal result under the retained ownership rules |
| Cancel | Cancel the target and attached descendants; preserve previously committed terminal decisions |
| Observation | Read-only Process snapshots, tree, results, and concise evidence records |

Normal Exit and explicit Fail still reject active attached children. Abnormal
failure performs child cleanup. Cancellation remains available as a Process
Action as well as a trusted Host operation: Operators must be able to manage the
work they create.

Keep the current lifecycle distinctions except REAPED: CREATED, READY, RUNNING,
WAITING, CANCELLING, FAILING, EXITED, FAILED, and CANCELLED. CREATED remains an
internal admission phase, not an inspectable successfully admitted Process.
Remove the REAPED enum member with the explicit reap API. Completed records remain
until the short-lived demonstration runtime is discarded. Retain the current
legal transitions under `docs/semantics.md`, using the detailed transition table
in `devdoc/semantics.md`, section 4, as supporting detail. The public contract
takes precedence if they disagree. Remove transitions to REAPED; cascading
cancellation also preserves any member's prior decision.

Keep the existing TerminalDecision and Kernel-owned finalizer where they enforce
one result and independent cleanup. Resource capacity must still count actual
live tasks, including cancellation-resistant tasks. These mechanisms are not
optional while the corresponding asynchronous behavior is retained.

## 5. Boundaries and authority

The design edition retains three distinct entry paths:

```text
Host bootstrap / administration -> small trusted Host facade -> Kernel
Operator or ordinary Process   -> Event / Action             -> Kernel
Kernel-authorized invocation   -> Resource bridge             -> Host resource
```

Console input remains a separate Host event bound to one Operator Process. It
does not acquire a Process source PID. The semantic backend remains a dependency
of the LLM Operator and never becomes a Kernel role.

The reduced Host facade is explicitly trusted local code. It does not expose a
ControlSession, claim remote authentication, or offer transport interruption and
reply guarantees. It provides bootstrap, inspect/tree, wait, cancel, and shutdown
through public Kernel methods. It cannot submit an arbitrary Process-originated
message. A future external transport must implement its own authenticated
contract before exposing these trusted methods.

Retain Principal, exact Permission matching, image execute ACL, requested versus
effective Authority, and parent-to-child authority reduction. In the reduced
policy, escalation is rejected; registered ApprovalArtifact workflows and partial
grant configuration move to the archived reference. Image and system ceilings
remain explicit. Process cancellation is permitted for self and attached
descendants, or for an unrelated target with its exact cancellation Permission.

## 6. Proposed file-level migration

This is the removal inventory to review before implementation. Tests are
migrated by retained behavior, not deleted wholesale because their module moves.

| Current files or area | Proposed disposition | Required retained evidence |
| --- | --- | --- |
| `kernel/kernel.py`, `_runtime.py`, `process.py` | Keep; remove only machinery made unreachable by contract reduction | Scheduling, finalization, failure/cancel races, result immutability |
| `kernel/actions.py`, `events.py` | Keep a reduced Action/Event ABI | Kernel-derived identity and explicit continuations |
| `kernel/operations.py` | Remove Control-only operations; relocate the remaining Action payloads to `actions.py` without duplicate definitions | One definition per guest operation |
| `control/` | Archive the complete package; replace active usage with a small trusted Host facade under `host/` | Host has no Process identity; administration cannot forge IPC |
| `cli/commands.py`, `cli/control.py`, `examples/control_runtime.py` | Remove the administration REPL from the design edition | Runnable demonstration remains available |
| `cli/rendering.py` | Replace general ControlReply rendering with explicit demo-report projection | Machine-readable output rejects arbitrary Host objects |
| `cli/main.py` | Retain a small demonstration entry point | Primary and extended offline commands |
| `software/image.py`, `catalog.py`, `program.py` | Keep; remove unused execution-profile fields and live unregister | Exact resolution and template-based composition |
| `security/` | Keep identity, exact authority, basic policy and admission evidence; remove approval registry and partial-grant options | Unauthorized child escalation is rejected |
| `resources/types.py`, `registry.py`, `bridge.py`, `memory.py` | Keep the minimal end-to-end resource proof | Denial before Host invocation; cancellation cannot deliver a late result |
| `resources/local.py` | Archive the local-filesystem proof | No filesystem-containment claim in the reduced edition |
| `resources/path.py` | Remove only after moving its portable `read_text` input validation into a retained resource module | In-memory and local proofs currently share this validator |
| `examples/resource_demo.py` | Reduce to an in-memory resource scenario | Same guest contract for success and permission denial |
| `host/console.py` | Keep | Human input does not forge Process IPC |
| `shells/`, `llm/base.py`, `llm/scripted.py` | Keep the three interchangeable Operators and deterministic backend | Same task and workers, different Operator image |
| `llm/openai.py` | Keep as an optional standalone boundary example, outside core imports | Real provider integration remains possible without changing Kernel |
| `values.py` | Keep where public data requires freezing | Published results and metadata cannot mutate afterward |
| Public `__init__.py` exports | Remove obsolete exports with the contract migration | No broken imports or accidental legacy API promises |
| `tests/test_control_protocol.py`, `test_control_gateway.py`, `test_cli_control.py` | Archive removed-protocol cases; migrate applicable identity/report tests | Core tests do not depend on archived Control objects |
| Remaining tests | Preserve invariant tests; adapt removed modes and obsolete APIs | Actual retained behavior remains covered |

An optional OpenAI example should be lazy-loaded, with its installation command
documented separately. Default setup and all primary demonstrations must work
without importing the provider SDK. Do not introduce a plugin framework to
support this single example.

## 7. Explicit behavioral reductions

- Keep attached children only. Remove Detach and detached spawning from this
  edition; independent roots are created by trusted bootstrap. This intentionally
  excludes demonstrations of children outliving their owners.
- Replace SELF/TREE selection with one ownership-cascading Cancel operation.
  Existing failed members retain their decisions and do not reject cancellation
  of the remaining subtree.
- Keep explicit Wait ALL. Remove Wait ANY and Spawn's implicit wait options;
  coordinator code receives Spawned and then returns Wait.
- Keep one ordinary Message payload form. Remove unused MessageKind distinctions
  after checking retained consumers.
- Keep operation completion/rejection Events where required. In particular,
  retaining asynchronous Cancel and Resource calls requires an explicit
  continuation; do not turn them into unobservable fire-and-forget actions.
- Remove explicit reap, live image unregister, and same-instance Kernel restart
  from the supported demonstration lifecycle. Each run uses a fresh runtime.
- Do not add PauseProcess, ResumeProcess, scheduling pause state, expanded Control
  execution/observation states, or mutation queue timeout semantics.

This is an explicit incompatible design-edition API revision. The implementation
should update imports, examples, tests, and public documentation together rather
than carrying a compatibility layer solely for the archived demo. Exact release
and tag names are selected at implementation time.

### 7.1 Migration details fixed by this proposal

Here, archive means preserve in the recoverable historical Git baseline, then
remove from the active source tree. Do not add an importable `archive/` package
or ship legacy tests with the design edition. Historical design documents may
remain under `devdoc/` with an explicit historical-status banner.

The new facade module is `semshell/host/admin.py`, exporting `HostAdmin`. Its
methods are `start()`, `spawn(spec, principal, authority_ceiling)`, `inspect(pid)`,
`tree(pid)`, `wait(pid)`, `cancel(pid, reason)`, and `stop()`. It wraps public Kernel
methods and introduces no request IDs, session state, additional process state,
or reply protocol. Bootstrap supplies Catalog, Policy, and ResourceRegistry when
constructing the runtime. `ConsoleBridge` remains in `host/console.py`.

The guest Action exports are `Spawn`, `Send`, `Wait`, `InvokeResource`, `Yield`,
`DiscoverImages`, `Cancel`, `Exit`, and `Fail`. Keep DiscoverImages because the
existing Operator examples resolve available software at runtime. Define their
payloads directly in `kernel/actions.py`:

| Action | Fields |
| --- | --- |
| Spawn | `specs` |
| Send | `target_pid`, `payload` |
| Wait | `child_pids` |
| InvokeResource | `binding_id`, `operation`, `input` |
| Yield | optional `next_event` |
| DiscoverImages | none |
| Cancel | `target_pid`, `reason` |
| Exit | `result` |
| Fail | `error` |

`SpawnProcesses`, `SendMessage`, and `CancelProcess` no longer serve as base or
alias definitions in `operations.py`. All ExternalControlOperation exports and
ControlRequest/Reply/Session/Gateway exports leave the active API. Remove Detach,
WaitMode, CancelMode, OwnershipMode, MessageKind, and the ProcessSpec ownership
selector; ordinary child admission is always attached. The trusted root spawn
path remains distinct from guest child admission.

Retain Started, Spawned, ChildrenCompleted, MessageReceived, ImagesDiscovered,
ConsoleInput, ContinuationEvent, OperationCompleted, OperationRejected,
ResourceCompleted, and ResourceRejected Events. Keep their current payloads
except Message: its retained fields are `source_pid`, `target_pid`, and `payload`.
The mailbox provides at-most-once acceptance within this runtime; no message-ID
deduplication or cross-run correlation is claimed.

Cancel's OperationCompleted follows terminal cleanup, as in the current public
summary; cancellation of the caller itself produces no continuation to that
caller. Explicit Fail retains the active-child rejection rule. A handler
exception, invalid returned Action, or result-freezing failure is abnormal
failure: commit FAILED, stop ordinary activation, clean up attached descendants,
then publish the result. Existing decisions cannot be overwritten. Retain the
current bounded cleanup and diagnostic rules for non-cooperative programs.

Remove ProcessSpec `args`, `env`, `cwd`, and `resource_limits` from this edition:
they do not configure the in-process execution demonstrated here. Retain image,
capability, provider, input, requested_authority, and metadata. Remove approval
with the approval workflow. Keep `demo --operator human|rule|llm`, add
`demo --scenario extended`, and remove the `control` CLI command. The optional
provider example uses its own documented Python entry point.

"No broken imports" means imports used by the active design edition and its
retained examples/tests. Historical third-party imports are intentionally not
compatible with this API revision.

## 8. Demonstrations and acceptance evidence

| Scenario | Reader-visible evidence | What it establishes |
| --- | --- | --- |
| Operator substitution | Human, Rule, and scripted LLM runs show the selected image, equivalent worker topology, and equal result | Operator choice does not alter Kernel or workers |
| Runtime composition | Coordinator creates two ordinary worker Processes, then explicitly waits for both | Composition uses software templates and Process operations |
| IPC provenance | A Process sends a message; receiver sees the Kernel-derived sender PID | Guest messages have authenticated semantic origin |
| Resource permission | The same request succeeds with permission and is rejected without it; rejected invocation count at the bridge is zero | Host access is mediated before invocation |
| Ownership cleanup | Cancel an owner during a blocked child/resource operation; show unique results and suppressed late output | Lifecycle management survives asynchronous completion |

The primary entry point remains `demo --operator human|rule|llm`. An extended
offline command can run the remaining scenarios sequentially. No network, API
key, Docker, arbitrary sleeps, or manual input timing is required to reproduce
the evidence.

Reports project only intentional public fields: image, PID/owner, state, result,
required/granted permission, and selected audit outcomes. A generic serializer
for arbitrary Python objects is unnecessary.

## 9. Implementation sequence

1. **Preserve and adopt scope.** Inspect the actual worktree and baseline validation.
   Preserve all intended source, tests, and documents in a recoverable commit and
   tag/branch before deletion; a tag alone cannot preserve uncommitted files.
   Synchronize the scope decisions listed in section 2. Do not silently commit
   unrelated user work.
2. **Establish the reduced demo path.** Make the primary and extended scenarios
   run through the reduced interfaces. Introduce the small trusted Host facade
   and report projection. Keep removed modules until their active consumers are
   migrated.
3. **Decouple the guest ABI.** Define guest Actions independently from Control
   operations and migrate Kernel, shell, example, and test consumers while
   preserving behavior.
4. **Reduce core behavior.** Migrate cancellation, ownership, Wait, messaging,
   ProcessSpec, Catalog, and policy as one explicit contract revision. Remove only
   internal branches made obsolete by these changes; retain lifecycle regression
   coverage.
5. **Remove secondary scope.** Remove the Control REPL/package and local filesystem
   proof after their consumers have migrated. Move the shared in-memory resource
   validator before removing its old module.
6. **Isolate the optional provider.** Remove the eager OpenAI import and default
   dependency while retaining the standalone provider-boundary example.
7. **Publish the reading path.** Update README, semantics, security model,
   codebase guide, TODO, and article evidence map. Mark historical specifications
   as archived rather than mixing them with the new current contract.
8. **Validate and freeze.** Run retained demonstrations, focused regression tests,
   the complete retained suite, Ruff, and strict mypy. Review the actual diff and
   run an independent reader check. Stop adding framework features after this gate.

The detailed checkpoints and rollback boundaries for this sequence are normative
in `design_edition_migration_stages.md`.

## 10. Completion criteria

- A reader can identify who chooses Actions, who authenticates identity, who
  owns lifecycle cleanup, and where Host authorization happens from the demo and
  short design guide.
- A new same-contract Operator requires only image/catalog assembly and its own
  program implementation; no Kernel role branch changes.
- Every active module supports a retained invariant, demonstration, or the
  explicitly optional provider example.
- Removed Control, detached ownership, wait-any, and filesystem guarantees are
  absent from current public claims and exports.
- Cancellation and failure still produce one terminal result, cannot be
  abandoned by an observer, and cannot reactivate completed Processes.
- Retained resource tasks release capacity exactly once; errors and output never
  expose arbitrary Host objects.
- Default demonstration setup is offline and provider-independent.
- All necessary verification passes, and the complete historical baseline can be
  recovered without restoring discarded temporary files.

No target line count is an acceptance criterion. Report the eventual source and
dependency reduction after implementation; do not promise a percentage before
the retained contract has been migrated and tested.

### Verification inventory

Keep `tests/test_kernel.py`, `test_kernel_lifecycle.py`,
`test_kernel_resources.py`, `test_public_types.py`, `test_resource_values.py`,
`test_authority_policy.py`, `test_catalog.py`, and `test_operator_demo.py`, adapting
only assertions for the explicitly changed contract. Remove local-file,
approval, detached, wait-any, reap, unregister, and restart cases after their
features are removed. Do not discard an entire retained test module because it
also contains one obsolete case.

Remove the three Control/CLI test modules listed in section 6 after moving
applicable Host identity checks to `tests/test_host_admin.py` and report/entry
point checks to `tests/test_demo_cli.py`. Keep the provider test as an optional
SDK-dependent test, skipped cleanly when that dependency is absent.

Run the three primary Operator commands and the extended command, then validate:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
```

Use the same available validation commands for the preserved baseline before
migration. Final validation must also run the primary demo in an environment
without the optional provider SDK. Record the actual outcomes; no baseline or
future validation result is asserted by this planning document.
