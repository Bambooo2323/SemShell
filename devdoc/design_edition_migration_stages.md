# Design Edition Staged Migration Plan

Date: 2026-09-10

Status: implementation staging proposal. It refines
[`design_edition_simplification_plan.md`](design_edition_simplification_plan.md)
without changing the current contract or source code.

## 1. Outcome

Migrate the current complete Python reference into a focused design edition
without losing the lifecycle fixes that make its claims credible.

The migration ends with one offline architecture demonstration, one extended
boundary demonstration, a small trusted Host facade, a reduced Process
Event/Action ABI, and tests tied only to retained claims. The historical
Control protocol and local filesystem proof remain recoverable from Git history
and are absent from the active package.

The work is divided into independently reviewable stages. Every stage must leave
the repository runnable and pass its declared gate before the next stage begins.
Do not combine stages merely to reduce the number of commits.

## 2. Preconditions and working rules

- Treat `docs/semantics.md` as authoritative until the contract migration stage
  explicitly replaces its affected sections.
- Preserve the current working tree before destructive removal. A baseline tag
  preserves only committed content, so uncommitted intended work must first be
  reviewed and committed or otherwise captured deliberately.
- Keep the current TerminalDecision, Kernel finalizer, reply/audit fixes, deep
  traversal fixes, resource slot accounting, and immutable result boundary until
  their consumers are migrated and equivalent retained tests pass.
- Make no production transport, persistence, container, pause/resume, or durable
  replay changes during this migration.
- Use English for new and modified source comments, tests, and documentation.
- At each gate, inspect the actual diff and keep unrelated user changes out of
  the stage.

The baseline preservation operation creates external Git history and is performed
only when implementation begins and the intended baseline contents are known.
Suggested names are `complete-reference` for the branch and
`complete-reference-YYYYMMDD` for the tag; final names are chosen at that time.

## 3. Stage overview

| Stage | Purpose | Mutation style | Exit artifact |
| --- | --- | --- | --- |
| 0 | Adopt scope and preserve the complete reference | Documentation and Git baseline | Recoverable complete implementation and accepted current contract |
| 1 | Establish the replacement presentation path | Additive | HostAdmin, explicit report projection, primary and extended offline demos |
| 2 | Decouple guest ABI from Control operations | Incompatible internal/public API migration | Actions defined independently; active code no longer imports `kernel.operations` |
| 3 | Reduce lifecycle and software semantics | Incompatible contract migration | Attached-only ownership, cascading cancel, Wait ALL, reduced ProcessSpec and policy |
| 4 | Remove secondary protocol and filesystem scope | Physical removal | No active Control REPL/package or LocalWorkspaceBridge |
| 5 | Isolate the optional provider adapter | Dependency boundary change | Offline default install/import path and optional OpenAI example |
| 6 | Publish and freeze the design edition | Documentation and validation | One coherent current contract, evidence map, and passing release gate |

Stages 2 and 3 are deliberately separate. Stage 2 changes type ownership while
preserving behavior; Stage 3 changes behavior after imports and call sites no
longer depend on the soon-to-be-removed Control vocabulary.

## 4. Stage 0 — Adopt scope and preserve baseline

### Changes

1. Review `git status`, the complete diff, untracked files, and current validation.
2. Decide which current changes belong to the complete reference baseline.
3. Preserve those contents in a normal commit, then create the recoverable branch
   and tag. Do not commit unrelated work merely to make the tree clean.
4. Update these decision sources to adopt the design edition:
   - `docs/reference-and-production.md`, section 11;
   - `devdoc/TODO.md`, sections 13–17;
   - `devdoc/lifecycle_rearchitecture.md`, phase 3 status.
5. Add proposal links where useful, while keeping Control, local filesystem, and
   current lifecycle specifications explicitly effective until their corresponding
   implementation stages change behavior. Do not add historical banners yet.

### Gate

- The baseline branch and tag resolve to the reviewed complete tree.
- The working branch contains only the scope-decision edits after baseline
  preservation.
- Current demos and the full current test suite still pass unchanged.
- The TODO names stages 1–6 as the only remaining implementation work.

### Rollback point

Return to the preserved baseline. No runtime or public API has changed.

### Current progress

On 2026-09-10, baseline characterization passed at Git `HEAD` `d295bc0`:

- Human, Rule, and scripted LLM primary demos each produced the same four-node
  topology and `("alpha", "beta")` result;
- pytest: 149 passed;
- Ruff: passed;
- strict mypy: 54 source files passed.

At characterization time, the only working-tree additions were this staged plan
and its parent simplification plan. The decision documents are now synchronized.
Baseline branch/tag creation remains pending, so Stage 0 is not complete.

## 5. Stage 1 — Establish the replacement presentation path

This stage is additive. It proves that the reduced presentation can replace the
REPL before any old path is removed.

### Changes

- Add `semshell/host/admin.py` with `HostAdmin` and the exact methods specified
  in the simplification plan: `start`, `spawn`, `inspect`, `tree`, `wait`,
  `cancel`, and `stop`.
- Keep HostAdmin as a thin trusted facade over public Kernel methods. It carries
  no SessionId, RequestId, PID identity, reply gate, retry, or transport state.
- Add an explicit demo-report projector. It serializes only the fields required
  by the architecture evidence and rejects unsupported values.
- Retain `demo --operator human|rule|llm` and add
  `demo --scenario extended`. The extended scenario covers:
  - Kernel-derived IPC source identity;
  - resource success and pre-invocation authority denial;
  - attached ownership cancellation with a suppressed late outcome.
- Keep the existing `control` command temporarily. Add no new commands to it.
- Add `tests/test_host_admin.py` and `tests/test_demo_cli.py`; extend
  `test_operator_demo.py` only where the same assertion belongs to the primary
  architecture proof.

### Gate

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario extended
```

- All four commands are deterministic, offline, and emit intentional JSON only.
- The three Operator runs retain equivalent topology and result.
- The extended report contains evidence for IPC, resource authorization, and
  cancellation without exposing PCB, bridge, task, or arbitrary Python objects.
- New HostAdmin tests prove it cannot originate Process IPC.
- The full existing suite, Ruff, and strict mypy pass.

### Rollback point

Remove the additive HostAdmin, report, scenario, and tests. Existing runtime and
Control behavior remain untouched.

### Completion record

Completed on 2026-09-10 without removing or changing the existing Control path:

- `HostAdmin` exposes only the seven planned administration methods and keeps
  the wrapped Kernel private;
- the primary and extended reports use closed, fail-closed projections;
- all four offline demo commands passed;
- pytest: 155 passed;
- Ruff: passed;
- strict mypy: 57 source files passed.

## 6. Stage 2 — Decouple guest ABI from Control operations

Current guest Actions alias or inherit Control-oriented payloads from
`kernel/operations.py`. Removing Control first would therefore break the core.
This stage establishes guest ownership of its own ABI while preserving current
behavior.

### Changes

1. Define `Spawn`, `Send`, `Cancel`, and the other retained guest payloads
   directly in `kernel/actions.py`.
2. Change Kernel Action dispatch, shells codec, examples, and guest tests to use
   those definitions.
3. Keep temporary Control operation classes in `kernel/operations.py`, but make
   them independent adapters rather than bases or aliases of guest Actions.
4. Adapt ControlGateway explicitly at its dispatch boundary. It may construct
   trusted Kernel calls but must not translate a request into a fake Process
   Action or source PID.
5. Update `kernel/__init__.py` and top-level exports so every active name resolves
   to one canonical definition.
6. Add an architecture test that active guest modules (`kernel/actions.py`,
   `shells/`, and architecture examples) do not import `kernel.operations` or
   `semshell.control`.

Stage 2 does not yet remove Detach, modes, ProcessSpec fields, Control classes,
or old CLI commands. Keeping behavior stable makes failures attributable to
type decoupling rather than semantic reduction.

### Gate

- Existing primary and extended demos are byte-for-byte equivalent in their
  intentional public fields.
- Current Control tests still pass through explicit adapter code.
- Guest ABI dependency test passes.
- Full pytest, Ruff, and strict mypy pass.

### Rollback point

Revert the canonical Action definitions and adapter mapping as one stage. No
behavioral migration has occurred.

### Completion record

Completed on 2026-09-10 without changing the Control protocol or guest behavior:

- guest `Send`, `Spawn`, `Cancel`, and `Detach` are canonical independent
  dataclasses in `kernel/actions.py`;
- Control operations remain independent payloads and ControlGateway dispatches
  them directly to trusted Kernel methods;
- architecture tests reject guest dependencies on `kernel.operations` and
  `semshell.control`;
- ControlRequest rejects all same-shape guest administration Actions;
- all four offline demo commands remained compatible;
- pytest: 159 passed;
- Ruff: passed;
- strict mypy: 57 source files passed.

## 7. Stage 3 — Reduce lifecycle and software semantics

This is the main incompatible contract change. Perform it as three sequential
work packages on one stage branch; each package receives focused validation.

### 3A. Attached-only ownership and cancellation

- Remove `Detach`, `DetachProcess`, `OwnershipMode`, and the ProcessSpec ownership
  field.
- Make every guest-spawned child attached. Trusted bootstrap creates independent
  roots by spawning without `parent_pid`.
- Replace SELF/TREE selection with `Cancel(target_pid, reason)` and
  `cancel(pid, reason)`, both covering the target and all attached descendants.
- During one non-yielding decision step, collect stable targets and preserve
  members with an existing terminal decision. A failing member cannot reject
  cancellation of the remaining subtree.
- Retain child-before-owner finalization, bounded cleanup, late Action/resource
  suppression, and exactly one ProcessResult per admitted Process.
- Migrate deterministic Spawn/Detach/Cancel race tests. Delete detached behavior
  tests only after replacement ownership tests pass.

Focused gate: deep attached tree, concurrent failure/cancel, self-cancel,
requester cancellation, Spawn/cancel ordering, and Kernel shutdown.

### 3B. Explicit Wait ALL and simplified messaging

- Remove `WaitMode`, Wait ANY, and `Spawn.wait` / `Spawn.wait_mode`.
- Make coordinators handle `Spawned`, then return `Wait(child_pids)` explicitly.
- Preserve empty waits, already-complete children, direct-child validation,
  exactly one `ChildrenCompleted`, and child-result ordering.
- Remove `MessageKind`, message ID, correlation ID, and message metadata from the
  design-edition ABI. Keep `source_pid`, `target_pid`, and `payload`.
- Preserve one authoritative mailbox entry and Kernel-derived source identity.
- Update the Human, Rule, and LLM Action codec and scripted responses together.

Focused gate: fan-out/fan-in for all Operators, wait rejection, empty/already
complete waits, FIFO message delivery, and forged-source prevention.

### 3C. Reduced ProcessSpec, Catalog, and policy

- Remove ProcessSpec `args`, `env`, `cwd`, `resource_limits`, ownership, and
  approval. Retain image/capability/provider, input, requested Authority, and
  metadata.
- Remove ApprovalArtifact registration and `allow_partial`. Requested Authority
  that cannot be granted exactly is rejected; do not silently reduce it.
- Retain parent authority ceiling, image authority ceiling and requirements,
  system authority, image execute ACL, and explainable admission records.
- Remove live `unregister_image` and explicit `reap`; remove REAPED from the
  ProcessState surface. Completed records live until the short-lived Kernel is
  discarded.
- Preserve exact and unambiguous Catalog resolution and immutable descriptors.

Focused gate: exact image and capability resolution, ambiguous provider,
multi-spawn atomicity, child escalation denial, image/system ceiling denial,
execute ACL, immutable results, and retained completed-tree observation.

### Stage 3 gate

- No active imports or exports remain for the removed types and fields.
- The primary and extended demos use only the reduced ABI.
- Focused gates for 3A–3C and the complete retained suite pass.
- `docs/semantics.md` and `docs/security-model.md` describe the implemented Stage 3
  ownership, cancellation, Wait, messaging, ProcessSpec, Catalog, and policy
  contract. Their still-active Control and LocalWorkspaceBridge statements remain
  current until Stage 4.
- Superseded lifecycle sections receive a historical banner only after their
  replacement contract is effective.

### Rollback point

Revert all three work packages together unless an intermediate commit is kept
only as an implementation checkpoint. The public contract must not expose a
mixture of old and new cancellation or ownership rules.

## 8. Stage 4 — Remove Control and local filesystem scope

The replacement facade and decoupled guest ABI must be complete before this
stage begins.

### Changes

- Remove active `semshell/control/`, `cli/commands.py`, `cli/control.py`,
  `examples/control_runtime.py`, and the `control` CLI subcommand.
- Remove remaining ExternalControlOperation and Control-only classes from
  `kernel/operations.py`; remove the file if it becomes empty.
- Remove general Control reply rendering from `cli/rendering.py`. Keep only the
  explicit demo-report projection, in the smallest fitting module.
- Remove `resources/local.py` and LocalWorkspaceBridge exports. First move the
  portable `read_text` input validator used by `resources/memory.py` from
  `resources/path.py` into a retained resource module; then remove `path.py`.
  Reduce `examples/resource_demo.py` to the in-memory proof.
- Remove `tests/test_control_protocol.py`, `test_control_gateway.py`, and
  `test_cli_control.py` after applicable assertions have migrated to HostAdmin
  and demo tests.
- Remove only LocalWorkspaceBridge cases from retained resource test modules.
- Mark Control and local-filesystem design documents historical and link them to
  the recoverable complete-reference tag.
- Remove Control and LocalWorkspaceBridge guarantees from current
  `docs/semantics.md`, `docs/security-model.md`, and `docs/codebase-guide.md` in the
  same stage as their implementation and exports.

### Gate

- `rg` finds no active import of `semshell.control`, `kernel.operations`,
  LocalWorkspaceBridge, or the removed CLI command outside historical documents.
- HostAdmin tests preserve the Host-versus-Process identity claim.
- In-memory resource tests preserve pre-invocation denial, input freezing,
  portable input validation, capacity accounting, cancellation, and late-result
  suppression.
- Primary and extended demos plus the complete retained suite pass.

### Rollback point

Restore the removed files from the Stage 3 checkpoint. Do not reconstruct them
manually; the complete reference remains available from the baseline.

## 9. Stage 5 — Isolate the optional OpenAI adapter

### Changes

- Remove eager `OpenAIResponsesBackend` import from `semshell/llm/__init__.py`.
- Move `openai` out of the default `requirements.txt`. Add an explicitly named
  optional requirements file, such as `requirements-openai.txt`, containing the
  provider dependency and including or documenting the base installation order.
- Retain `llm/openai.py` as a standalone provider-boundary example and keep its
  normalized model-neutral return type.
- Ensure the primary package, tests, and demonstrations import and run when the
  OpenAI SDK is absent.
- Keep provider tests separate and skip them only when the optional dependency
  is unavailable; the scripted LLM test remains mandatory.

### Gate

- Create a clean temporary virtual environment with only default requirements;
  import `semshell`, run all four demos, and run the mandatory suite.
- In the project environment with optional requirements installed, run the
  adapter test using its fake client. No live API request is part of validation.
- Ruff and strict mypy pass for the active package. If static checking the
  optional module requires the SDK, document and run that check in the optional
  environment.

### Rollback point

Restore the eager export and dependency declaration. No Kernel contract changes
in this stage.

## 10. Stage 6 — Publish and freeze

### Changes

- Rewrite README around one 60-second command sequence and one extended offline
  path.
- Update `docs/design.md`, `semantics.md`, `security-model.md`, and
  `codebase-guide.md` to contain only active guarantees.
- Update `docs/reference-and-production.md` so the design edition and separate
  Linux/OCI runtime boundary remain clear.
- Update `devdoc/TODO.md` and the article evidence map with final commands,
  outputs, tests, and intentionally removed capabilities.
- Add historical banners to retained v0.1–v0.3, Control, resource filesystem,
  lifecycle migration, and pruning plans. Historical documents must not appear
  to be the current contract.
- Measure and report final active source files, lines, default dependencies, and
  test count as descriptive results rather than success targets.
- Run a context-free reader review against README, current design documents, and
  command output.

### Final validation

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator human
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator rule
.\.venv\Scripts\python.exe -m semshell.cli.main demo --operator llm
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario extended
.\.venv\Scripts\python.exe -B -m pytest -q -o cache_dir=.venv/.cache/pytest
.\.venv\Scripts\python.exe -m ruff check --no-cache --target-version py311 semshell tests
.\.venv\Scripts\python.exe -m mypy --strict --cache-dir .venv/.cache/mypy semshell
```

Run the offline-import check from Stage 5 in addition to these commands.

### Completion criteria

- A reader can identify the Action decision maker, authenticated PID source,
  lifecycle owner, and Host authorization point without reading Kernel internals.
- Replacing an Operator changes only its Program/image assembly and does not add
  a Kernel role branch.
- Every active module supports a retained demonstration, invariant, or optional
  provider example.
- Current exports and documents contain none of the removed API promises.
- Historical behavior remains recoverable from the preserved baseline.
- All final validation and independent reader checks pass.

## 11. Stage tracking template

Use this block in `devdoc/TODO.md` for each stage when implementation begins:

```markdown
### Stage N — Name

- [ ] Baseline and affected files reviewed.
- [ ] Contract changes written before incompatible code changes.
- [ ] Implementation and consumer migration complete.
- [ ] Focused tests pass.
- [ ] Full required validation passes.
- [ ] Diff and public exports reviewed.
- [ ] Stage checkpoint recorded.

Evidence:
- Commands:
- Tests:
- Diff summary:
- Deferred items:
```

Do not mark a stage complete because obsolete tests were removed. Its retained
replacement evidence and declared gate must pass first.
