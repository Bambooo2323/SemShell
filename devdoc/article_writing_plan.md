# SemShell Article Writing Plan

中文部分为用户注释。

## 1. Writing decision

The next deliverable is a concise English technical essay supported by this
repository as an executable reference design. The essay is not API
documentation, a framework tutorial, a benchmark report, or a claim that the
Python prototype is a production runtime.

Working audience:

- engineers building agent runtimes, coding agents, and orchestration systems;
- systems engineers interested in process, capability, and control-plane
  abstractions;
- readers who know tool calling but do not know the SemShell vocabulary.

Desired reader outcome:

> A reader should understand why LLMs, tools, coordinators, and human-facing
> shells can be modeled as equal executable Processes, what this changes in
> engineering and management, and how the idea maps onto Linux/OCI without
> pretending to replace the operating-system kernel.

Target length: roughly 2,500–4,000 words plus two or three small diagrams.

## 2. Central thesis

Recommended title:

> **LLMs Are Programs, Not Kernels: A Process-Centric Runtime for Agentic
> Software**

One-sentence thesis:

> Agent software becomes easier to reason about when the runtime treats
> LLM-backed programs, deterministic tools, coordinators, memory services, and
> human-facing shells as equal Processes, while an LLM-backed Process may
> temporarily exercise the Operator role under delegated Authority.

The shortest supporting argument is:

1. A traditional Agent application usually gives the LLM loop structural
   ownership of tools, memory, subagents, and orchestration.
2. SemShell moves execution structure into explicit ProcessImage, Process,
   Event, Action, ownership, lifecycle, and Authority values.
3. HumanShell, RuleShell, and LLMShell then become replaceable programs using
   the same contract; none requires a Kernel role branch.
4. The reference repository proves the semantics in Python. A production
   implementation should delegate execution and isolation to Linux and an OCI
   runtime while preserving the language-neutral contract.

## 3. Claims and non-claims

### Claims the article should defend

- LLM, tool, memory, coordinator, and shell are software roles rather than
  privileged Kernel entity types.
- Operator is a replaceable role played by a Process, not a synonym for the
  user, Principal, or Kernel.
- Structured Event/Action exchange makes execution decisions explicit without
  imposing one Agent loop, graph, or prompting strategy on the Kernel.
- Process identity, ownership, cancellation, results, and Authority provide a
  useful engineering and management vocabulary for agentic software.
- Host administration, Process IPC, model-provider access, and Host resources are
  distinct boundaries.
- A Python reference state machine and a production Linux/OCI runtime are two
  products sharing semantics, not two layers that should be merged into one
  scheduler.

### Claims the article must not make

- that SemShell improves inference speed or scheduling performance;
- that the Python runtime is a security sandbox or production scheduler;
- that a container alone is a complete hostile multi-tenant boundary;
- that the design is POSIX-compatible or implements a new Linux kernel;
- that every Agent application should be decomposed into many containers;
- that the current wire protocol, recovery ordering, or result/exit precedence
  is already production-complete;
- that existing Agent frameworks literally implement the same hierarchy or
  share one internal design.

The article may compare architectural tendencies, but it should identify
specific examples and sources instead of describing all Agent frameworks as a
single category.

## 4. Proposed article structure

### 4.1 The person at the terminal became software

Open with the CLI analogy. In a traditional terminal, a human interprets a
goal, chooses executables, supplies arguments, observes results, and decides
what runs next. An LLM-backed Shell Process can assume part of that Operator
work without becoming the Kernel or the user.

End this section with:

> The LLM is not the kernel, and it is not the user. It is an executable
> Process that may exercise the Operator role under delegated Authority.

Evidence source: `devdoc/llm_cli_os_design_draft.md`, sections 1–4 and 10–11.

### 4.2 Flatten the Agent hierarchy

Contrast an LLM-owned application graph with the SemShell view:

```text
LLM/application loop                 Process-centric runtime
├── tools                            Kernel
├── memory                           ├── Process
├── subagents                        ├── Process
└── orchestration                    └── Process
```

Explain that flattening does not mean every program has the same behavior or
Authority. It means the execution substrate uses one entity type and one
lifecycle vocabulary.

Evidence sources: `docs/design.md`, "Flattened execution model";
`tests/test_operator_demo.py::test_kernel_has_no_operator_role_imports_or_branches`.

### 4.3 Separate software, execution, identity, and permission

Introduce only the values needed for the argument:

```text
ProcessImage + ProcessSpec -> Process
Principal -> authorizes Process
Process -> carries effective Authority
```

Explain why requested Authority is a request rather than a grant and why
ProcessImage execution ACL is separate from runtime Authority.

Evidence sources: `docs/semantics.md`, "Core entities" and "Spawn and
authority"; `tests/test_public_types.py`; `tests/test_authority_policy.py`.

### 4.4 Replace the fixed Agent loop with Event/Action execution

Show the activation cycle:

```text
Event -> ProcessProgram.handle() -> one Action -> Kernel transition
```

Use Spawn, Wait, DiscoverImages, InvokeResource, Exit, and Fail as examples.
Clarify that ReAct, graphs, planning, and model invocation remain valid
user-space strategies; they simply stop defining the runtime substrate.

Evidence sources: `docs/design.md`, "Event/Action ABI";
`docs/codebase-guide.md`, "Guest Process activation".

### 4.5 The executable proof: three equal Operators

Describe the deterministic demonstration:

```text
Operator Process
└── demo.coordinator
    ├── demo.echo("alpha")
    └── demo.echo("beta")
```

HumanShell, RuleShell, and LLMShell select the same structured Action through
the same Process ABI. Only the Operator ProcessImage changes. The LLM path uses
a scripted backend, so the architecture claim is tested without making a model
quality claim.

Evidence sources: the README 60-second proof;
`semshell/examples/architecture_demo.py`;
`tests/test_operator_demo.py::test_same_task_uses_replaceable_operator_processes`.

### 4.6 Four boundaries that should not collapse

Explain the differences among:

| Boundary | Identity source | Direction | Purpose |
| --- | --- | --- | --- |
| Process ABI | Kernel-authenticated PID | Event/Action | guest execution |
| HostAdmin | trusted bootstrap Principal and ceiling; no PID | lifecycle methods | root administration |
| Host resource bridge | Kernel-authenticated invocation | invoke/result | scoped external capability |
| Model backend | Process-owned adapter | provider-neutral request/result | optional semantic computation |

Use the absence of Host administration `send` as a compact example: an external
client has no authentic Process PID, so it cannot fabricate Process IPC.

Evidence sources: `docs/codebase-guide.md`, "Architecture";
`docs/semantics.md`, "Host administration";
`tests/test_host_admin.py::test_host_admin_exposes_only_the_closed_management_surface`.

### 4.7 Why use an OS metaphor if Linux already exists?

Answer directly: SemShell owns semantic meaning, not CPU scheduling, memory,
filesystems, signals, or namespaces. In production, Linux/OCI owns execution
mechanism; the SemShell control plane owns logical identity, admission,
Authority, ownership, structured results, and audit meaning.

Use one container execution per SemShell Process as the initial mapping, not as
a universal or permanent optimization claim.

Evidence source: `docs/reference-and-production.md`, sections 1–8.

### 4.8 Why is this framing uncommon?

Treat this as a researched discussion, not an unsupported fact. Candidate
hypotheses to investigate:

- tool-calling APIs naturally encourage an LLM-centered application shape;
- application frameworks optimize for fast composition inside one process;
- explicit process lifecycle, Authority, and recovery semantics cost more
  upfront than a local orchestration loop;
- most examples optimize task completion rather than runtime substitutability
  and operational legibility;
- graph and actor systems solve adjacent problems, making a new process
  vocabulary look unnecessary until Host boundaries and multiple Operators
  matter.

The final article should keep only hypotheses supported by named primary
sources or clearly label them as the author's interpretation.

### 4.9 What the prototype proves—and what comes next

Close by separating the complete reference proof from future application work.
The reference repository demonstrates role neutrality, lifecycle, Authority,
Host resource boundaries, and Host administration. The next design artifact is a
language-neutral worker protocol. The production runtime belongs in a separate
repository using Linux/OCI mechanisms.

Name the two open semantics explicitly:

1. admission/create/persist/start crash-recovery ordering;
2. structured worker-result versus conflicting runtime-exit precedence.

Evidence source: `docs/reference-and-production.md`, sections 9–12.

## 5. Evidence map

Final reproducible commands, expected outputs, measured source size, dependency
counts, removed capabilities, and review status are recorded in
[the Stage 6 validation record](../docs/design-edition-validation.md).

| Article statement | Executable evidence | Normative/descriptive source |
| --- | --- | --- |
| Operators are replaceable Processes | `tests/test_operator_demo.py` | `docs/design.md` |
| Kernel has no Operator-specific branch | architecture test in `test_operator_demo.py` | `docs/design.md` |
| Image and Process are distinct | `tests/test_public_types.py` | `docs/semantics.md` |
| Child Authority cannot silently escalate | `tests/test_authority_policy.py` | `docs/semantics.md` |
| Attached ownership and cancellation are explicit | `tests/test_kernel.py` | `docs/semantics.md` |
| Host resources use a generic bridge | `tests/test_kernel_resources.py` | `docs/security-model.md` |
| External clients cannot forge Process IPC | `tests/test_host_admin.py` | `docs/semantics.md` |
| Demo reports expose identity, denial, and cancellation | `tests/test_demo_cli.py` | `docs/codebase-guide.md` |
| Provider SDK values stay outside Kernel | `tests/test_openai_backend.py` | README boundary proof |
| Python and production runtime are separate | not an implementation claim | `docs/reference-and-production.md` |

Tests are evidence for the reference model's behavior. They are not evidence
that a production container backend already exists.

## 6. Terminology contract

Use these terms consistently:

- **Kernel**: the semantic state machine that admits operations and owns
  logical Process state; capitalize when referring to the SemShell component.
- **Linux kernel**: the real operating-system kernel.
- **Process**: a SemShell logical execution, not necessarily one Linux PID.
- **ProcessImage**: immutable logical software definition.
- **ProcessSpec**: single-use execution request.
- **Operator**: a role played by a Process.
- **Principal**: authenticated identity or authorization source.
- **Authority**: exact permission set carried by one Process execution.
- **HostAdmin**: trusted root lifecycle facade with no Process PID.
- **Process ABI**: Event/Action guest execution contract.
- **Host resource bridge**: trusted adapter to a scoped external resource.
- **reference runtime/design**: the Python executable specification.
- **production runtime**: the future Linux/OCI application repository.

Avoid using `agent`, `tool`, `memory`, or `coordinator` as Kernel types. They may
be used as descriptions of software roles.

## 7. Planned figures

Keep diagrams small enough to remain legible in a GitHub article.

1. **Flattened architecture**: LLM-owned hierarchy versus Kernel with equal
   Processes.
2. **Identity and execution**: Principal delegates Authority to an Operator
   Process, which emits Actions that create other Processes.
3. **Reference-to-production mapping**: Python semantic oracle on one side;
   control plane, OCI runtime, and Linux kernel on the other; versioned schemas
   and conformance fixtures between them.

The Process-tree output from the 60-second demonstration can serve as a code
block rather than a fourth diagram.

## 8. Source and research plan

### Repository sources already ready

- `README.md`: reproduction path and boundary-proof entry points;
- `docs/design.md`: short architecture argument;
- `docs/semantics.md`: normative reference semantics;
- `docs/security-model.md`: present trust boundary and non-claims;
- `docs/codebase-guide.md`: implementation navigation and evidence paths;
- `docs/reference-and-production.md`: Linux/OCI production mapping;
- `devdoc/llm_cli_os_design_draft.md`: original motivation and terminology.

### External primary sources to collect before drafting comparisons

- official tool-calling and Agent SDK documentation for concrete examples of
  LLM-centered composition;
- official Codex documentation or source for its process, sandbox, tool, and
  approval boundaries;
- OCI Runtime Specification for container configuration and lifecycle;
- Linux/Docker documentation for namespaces, cgroups, signals, bind mounts,
  and network isolation;
- primary actor-model or workflow-system documentation if the article compares
  SemShell with actors, DAGs, or workflow engines.

Do not use secondary summaries when the primary specification or project
documentation is available. Keep source quotations short; prefer paraphrase and
link each factual comparison near the relevant sentence.

## 9. Writing sequence

Draft in this order:

1. sections 4.2–4.4: flattened model and technical mechanism;
2. section 4.5: executable proof;
3. sections 4.6–4.7: boundaries and production mapping;
4. section 4.8: researched explanation of why the framing is uncommon;
5. sections 4.1 and 4.9: opening and conclusion;
6. title, abstract, and repository landing copy last.

This order prevents the opening from promising more than the technical body
can defend.

## 10. Publication readiness checklist

- [x] Active design-edition scope is defined through Stage 5; Stage 6 evidence is
  recorded in `docs/design-edition-validation.md`.
- [x] Reference and production responsibilities are separated.
- [x] README provides one short deterministic reproduction path.
- [x] Public architecture, semantics, security, and codebase guides agree.
- [x] The complete offline suite passes.
- [ ] Independent reader review of the final design edition remains pending.
- [ ] Collect primary sources for ecosystem and Codex comparisons.
- [ ] Draft the article section by section.
- [ ] Verify every external comparison against its cited source.
- [ ] Run context-free reader tests on the complete article.
- [ ] Decide the new repository name, license, and publication location.

## 11. Definition of done for the article

The article is ready when a reader unfamiliar with the repository can answer:

1. What exactly is being flattened?
2. Why is the LLM neither Kernel nor Principal?
3. How are HumanShell, RuleShell, and LLMShell interchangeable?
4. What does Event/Action replace, and what does it leave to user-space code?
5. Why can Host administration not impersonate a Process?
6. What does the Python reference implementation prove?
7. What must Linux/OCI implement in production?
8. Which production semantics are still open?
9. What engineering advantage is claimed if performance is not the goal?

Answers must be recoverable from the article without requiring the reader to
inspect the source tree first.
