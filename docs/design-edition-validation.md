# Design edition validation and handoff

Date: 2026-09-15. Stage 6 documentation and executable gates are ready for review.
Independent reader sign-off remains pending. No release commit, release tag,
remote publication, or independent review is claimed by this record.

## Maintenance review — 2026-09-23

The sections dated 2026-09-15 below retain their historical measurements.
The current checklist is [devdoc/TODO.md](../devdoc/TODO.md); the previous
roadmap is preserved as [historical TODO](../devdoc/TODO-history.md).

This review corrected shallow metadata freezing in image, capability, and
resource descriptors, and an Authority report sorting failure when a capability
has both unscoped and string-scoped permissions. Eleven added regression cases
failed before the fixes and pass after them. Nested metadata now uses immutable
copies; changing the original containers cannot change the registered definitions.

Validation used the existing Python 3.13.5 environment, without installing
dependencies or calling a live model API:

| Check | Result |
| --- | --- |
| Full pytest suite | 124 passed |
| Ruff, package and tests | Passed |
| Default strict mypy, excluding the optional adapter | 43 source files passed |
| Full strict mypy, including the installed optional adapter | 44 source files passed |
| `pip check` | No broken requirements found |
| Five separate CLI runs: human, rule, llm, extended, delegation | Valid JSON; extended identity, denial, cancellation and late-result evidence matched expectations |

The existing environment includes OpenAI SDK 3.3.1; its tests use a fake client.
The current source tree contains 44 package Python files and 13 test modules.
Python 3.11/3.12 compatibility and a freshly created SDK-free environment were
not re-tested in this review. The earlier default-environment record below is
historical evidence, not a claim that those checks were repeated today.
Independent reader sign-off, the fourth Operator scenario, and publication
remain open; this maintenance review does not close those gates.

## Reproduce

Follow [README](../README.md) for Python 3.11+ setup, the three primary Operator
commands, the extended demo, and default and optional validation commands.
The primary commands return `["alpha", "beta"]` with owners `[null, 1, 2, 2]`.
The extended command reports authenticated IPC, zero bridge invocations on
Authority denial, owner and child cancellation, one child result publication,
and suppression of the late resource result.

## Validation on the reviewed working tree

| Environment / check | Result |
| --- | --- |
| Default requirements, SDK absence asserted with `find_spec('openai')` | Package and CLI import passed |
| Default pytest | 106 passed, 1 optional provider module skipped |
| Optional SDK environment pytest | 107 passed, including fake-client provider test |
| Four separate CLI subprocesses in default environment | All exited successfully; JSON results checked |
| Ruff, active package and tests | Passed |
| Default strict mypy, excluding `semshell/llm/openai.py` | 42 source files passed |
| Optional strict mypy, entire package | 43 source files passed |

The default environment was created with only `requirements.txt` during Stage 5
and reused for this review. It still has no OpenAI SDK. The project `.venv`
contains the optional SDK. No live model API calls were made.

## Measured size

Counting `semshell/**/*.py`, including package markers and the optional adapter:
43 source files and 4,196 physical lines, including comments and blank lines.
There are 12 test modules. Default direct requirements are `mypy`, `pytest`,
`pytest-asyncio`, and `ruff`; these are validation tools. The default runtime
uses the standard library. `requirements-openai.txt` adds one direct optional
provider dependency and includes the default requirements. Transitive package
counts are not represented by these direct-dependency figures.

## Evidence for readers and article authors

| Question or claim | Where a reader can verify it |
| --- | --- |
| Who chooses an Action? | README primary proof and `docs/design.md`: the Operator Process; the coordinator subsequently chooses worker Actions |
| Where does a sender PID come from? | `docs/semantics.md`, IPC; extended `ipc.source_authenticated`; `tests/test_demo_cli.py` |
| Who owns lifecycle cleanup? | Attached owner edges plus Kernel finalizers; `docs/semantics.md`, Cancellation and completion; `tests/test_kernel_lifecycle.py` |
| Where is Host access authorized? | Kernel binding/Permission check before bridge invocation; extended denied invocation count; `tests/test_kernel_resources.py` |
| What changes when an Operator is replaced? | Operator Program/image assembly; coordinator and workers remain shared; `tests/test_operator_demo.py` |
| Can HostAdmin impersonate a sender? | Its closed method surface contains no Send; `tests/test_host_admin.py` |
| Does the Kernel recognize Operator roles? | `test_kernel_has_no_operator_role_imports_or_branches` and the shared four-node demo topology |
| Is this an OS sandbox? | `docs/security-model.md`: trusted Python code shares one interpreter; production containment is separate |

The current replaceability proof covers the three shipped Operator images. A
separate fourth, newly registered Operator scenario has not been added. Tests
prove the named mechanisms and examples, not arbitrary replacement programs or
performance improvements over other frameworks.

## Retained and removed scope

Retained: Process/Event/Action, attached ownership, cascading cancellation,
explicit Wait ALL, exact Authority, Catalog descriptors, immutable results,
HostAdmin, ConsoleBridge, in-memory resource mediation, and an optional provider
adapter. Each active package is mapped in [the codebase guide](codebase-guide.md).

Removed: Control protocol and REPL, local filesystem bridge, Detach and ownership
modes, cancellation modes, Wait ANY and implicit spawn waiting, message metadata,
approval artifacts and partial grants, live Catalog unregistration, and explicit
reaping. Production execution, transports, persistence, and containment remain
outside this repository's implementation scope.

The pre-removal checkpoint is commit
`73c133d7a55bfec349708a276b8f91fb3011844a`. Historical plans named Git tag
`complete-reference-20260915` and branch `complete-reference`; neither ref is
present in the local checkout reviewed on 2026-09-23. Their remote availability
was not checked. Use the verified commit directly for local inspection:

```powershell
git show 73c133d7a55bfec349708a276b8f91fb3011844a:semshell/control/gateway.py
```

It preserves Control and filesystem code with the Stage 3 contract. Earlier API
contracts are in its ancestors; the checkpoint is not a snapshot of every old API.

## Reader review and freeze status

Maintainer self-review used README, current docs, and CLI output to answer the
questions above. It found and corrected the missing extended README command,
obsolete Control evidence links, and the distinction between pre-invocation
JSON freezing and bridge-local path validation.

An independent reader should now use only README, current docs, and command
output to explain: the Action decision maker, authenticated PID source,
lifecycle owner, and Host authorization point. Record the reader, date, answers,
and any unresolved confusion here before marking Stage 6 fully complete.

- [x] Documentation and executable validation prepared.
- [x] Current scope and historical recovery point documented.
- [ ] Independent reader review recorded.
- [ ] Final Stage 6 sign-off.
