# Delegated-authority conversation

This example exercises ordinary Process programs, authenticated IPC, resource
admission, and parent-bounded authority without adding Kernel role branches.

```powershell
.\.venv\Scripts\python.exe -m semshell.cli.main demo --scenario delegation
```

## Scenario

The Host bootstraps a UserShell with permission to read `delegation.report` and
delivers a text dialogue through its bound ConsoleBridge. UserShell creates
llm1 with empty Authority. Its scripted model requests analysis of a restricted
project report, while two ordinary tools count words and characters in the
dialogue.

The following are intentional negative probes, not autonomous model choices:

1. llm1 invokes the report resource without permission. The Kernel rejects it
   before the bridge runs.
2. llm1 requests an llm2 child with report permission. Admission rejects the
   authority increase and publishes no child Process.
3. After authorized creation by UserShell, llm2 tries another binding,
   `delegation.other`. Its report permission does not cover that resource.

Between probes 2 and 3, llm1 sends a structured delegation request to UserShell.
The shell checks the Kernel-supplied sender PID, request shape, request ID, and
an exact binding allowlist. Its configured approval policy decides whether to
create llm2. The request cannot choose a factory, image, or arbitrary grant.
Kernel admission independently checks UserShell's existing authority.

The successful ownership tree is:

```text
UserShell                         [report-read permission]
├── llm1                          [empty Authority]
│   ├── text tool: words           [empty Authority]
│   └── text tool: characters      [empty Authority]
└── llm2                          [report-read permission]
```

llm2 is llm1's collaborator but UserShell's child. UserShell waits for llm2,
then sends a correlated result to llm1. llm1 accepts replies only from its owner,
waits for its own tool children, calls its backend to summarize, and exits.
It never waits directly for a sibling and never acquires report permission.

UserShell remains `WAITING` after the response so the report shows the open
conversation state. This example handles one dialogue per shell instance; it
does not implement a general conversation frontend. After collecting the
report, the Host shuts down the Kernel and cleans up the shell. Finished child
results are preserved by the existing lifecycle rules.

## Evidence

| JSON field | Successful scenario |
| --- | --- |
| `backend` | `scripted`; all model outputs are offline fixtures |
| `result.delegation.status` | `completed` |
| `tree` | five Processes; llm1 and llm2 share UserShell as owner |
| `authority_decisions` | llm1's privileged spawn is denied; UserShell's is allowed |
| `resource_audit` | llm1/report and llm2/other are rejected with `resource.authority_denied` |
| `bridge_invocations` | report: 1, other: 0 |
| `model_calls` | llm1: 2, llm2: 1 |
| `trace` | both tools are running at approval and at llm2 startup |

The tools use a shared, Host-injected event gate to make overlap deterministic.
They start before approval and are released when llm2 starts, or when delegation
is refused. This proves overlapping execution lifetimes under asyncio; it is
not a CPU parallelism or latency benchmark. The fixture also collects
diagnostics and does not grant guest access to the Kernel.

The resource audit and admission decisions come from the Kernel. The trace
records application-level events. Keep these two kinds of evidence distinct.

## Other outcomes

The Python entry point supports rejection cases without changing the Kernel:

```python
from semshell.examples.delegation_demo import run_delegation_demo
from semshell.security import Authority

# Simulate declining the delegation request.
report = await run_delegation_demo(approve=False)

# A model asks for a binding outside UserShell's allowlist.
report = await run_delegation_demo(requested_binding="delegation.other")

# UserShell approves, but its execution does not hold the requested permission.
report = await run_delegation_demo(shell_authority=Authority.empty())
```

These paths finish the unprivileged tools and report denied delegation without
creating llm2 or accessing either resource. The final case demonstrates that
UserShell approval cannot manufacture authority.

## Extending the example

The implementation is in
[`semshell/examples/delegation_demo.py`](../semshell/examples/delegation_demo.py):

- `DelegationUserShell` implements the dialogue and approval protocol with
  ordinary Spawn, Wait, Send, and Yield Actions.
- `DelegatingLLM` implements llm1's plan, deliberate denial probes, request, and
  result aggregation.
- `RestrictedLLM` implements llm2's authorized read, scope probe, and analysis.
- `ParallelTextTool` implements deterministic worker behavior.
- `run_delegation_demo` registers ProcessImages, injects model backends and
  resource bridges, bootstraps the session, and projects evidence.

Both LLM programs depend on `SemanticBackend`. The runner currently supplies
`ScriptedSemanticBackend`; a real-model experiment needs model configuration,
appropriate decision parsing, and an explicit approval frontend or policy.
The fixed summary text tests model-call integration rather than model quality.

Adding a worker requires a ProcessProgram implementation, a ProcessImage
registration, and a ProcessSpec in the calling program. The example uses exact
image references so discovery and provider selection do not obscure the
authority flow. It adds no new runtime operation or automatic permission grant.

Validation covers the successful tree and all three probes, refusal, an
out-of-allowlist request, insufficient shell authority, an unrelated IPC sender,
and the CLI report:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_delegation_demo.py
```
