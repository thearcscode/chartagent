# 15. The sandbox runs programs we did not write, and receives only transform output

- **Status:** Accepted
- **Date:** 2026-08-28
- **Settled on:** [#6](https://github.com/thearcscode/chartagent/issues/6)
- **Builds on:** ADR-0001 (pin Flint; compile in the client; no CPython JS engine),
  ADR-0003 (rasterise in a browser, behind a `Rasteriser` protocol in an optional extra),
  ADR-0005 (`bind` is the public seam; `__all__` is the contract; no knobs on a protocol),
  ADR-0008 (the transform menu and its three `raw_sql` locks),
  ADR-0011 (the profile contract; profiling runs in-process)
- **Amends:** ADR-0005 Decision 6 — recorded as a dated erratum in place and listed under
  *What this amends*. Errata also on PRD §7.1, §7.5, §7.6, §9 P0.6 and §13.

## Context

PRD §7.5 describes a sandbox with four jobs, a four-tier isolation ladder, and a
`SandboxBackend` protocol shaped `upload(path)` / `run(code) -> {stdout, stderr, artifacts}`
/ `download(path)`. It was written before ADR-0003, ADR-0005, ADR-0008 and ADR-0011, and
three of its four jobs have since been decided somewhere else.

### What the later ADRs took, and what they did not

| §7.5 puts in the sandbox | Where it actually runs |
| --- | --- |
| profiling scans | **in-process** (ADR-0011) — hostile-Parquet recorded as *accepted and unsolved*, explicitly not handled by §7.5 |
| transform / `raw_sql` on both rails | **in-process** (ADR-0005 D6 at P0; this ADR extends it to P1), contained by ADR-0008's three locks |
| custom-rail generated code | **the sandbox** — this ADR |
| rasterisation + Playwright, `web` profile | split: **review-gate rasterisation** left for a browser behind ADR-0003's `Rasteriser`; the **custom-rail `web` profile** did not move and is still untrusted generated JS |

That last row is the one it is easy to get wrong, and this ADR states it explicitly because
an earlier reading of ADR-0003 collapsed the two. ADR-0003 took a *trusted* harness
rasterising *our* envelope in an optional extra. The custom rail's `web` profile is
generated JavaScript that must run isolated in order to produce the chart at all. It is
still code we did not write, and it is still this protocol's problem — **the web profile is
a §9 P1 requirement in Fast follows; phase P2 ships the python profile only** (§11's note:
a bare P0/P1/P2 is a *phase*, a P0.n/P1/P2 in §9 is a *requirement priority*, and the two
are not aligned).

> **Reversed — 2026-08-28 ([#57](https://github.com/thearcscode/chartagent/issues/57),
> ADR-0017 D2).** The phase ordering in the sentence above is backwards: **`web` is the
> phase-P2 custom rail and `python` is the later widening.** The paragraph's substantive
> point stands — the custom rail's `web` profile is untrusted generated JS and did not move
> with ADR-0003's rasterisation — but its containment is a **sandboxed iframe**, not this
> protocol, so *"still this protocol's problem"* is no longer true either. See Decision 7's
> erratum below; noted here because Context is read on its own.

So the sandbox's remaining job is one job, and the whole ADR follows from naming it: it
contains **programs we did not write**. It does not contain the data vector and it does not
contain the transform.

### What already exists, measured

`deepagents` is in the base install (#19), and it already defines a
`SandboxBackendProtocol` — the same name PRD §7.5 wants. Measured against the published
package on 2026-08-28:

- Latest is **0.7.10**, with **eleven releases since 0.7.0 on 29 July**. `docs/research/python-arrow.md`
  surveyed **0.6.12**, a minor version behind.
- `protocol.py` exists at 0.6.12 and at 0.7.10, so the collision does not depend on the pin.
- Diffing its signatures across that window, the churn is **asymmetric**: `SandboxBackendProtocol`
  (`id`, `execute`, `aexecute`) is **unchanged**, while `BackendProtocol` **lost six public
  methods** (`ls_info`, `als_info`, `glob_info`, `aglob_info`, `grep_raw`, `agrep_raw`) and
  gained two (`delete`, `adelete`).
- `BaseSandbox` implements every file operation on top of `execute()`, so a provider
  implements one method.
- `ExecuteResponse` is `output` (stdout and stderr **combined**), `exit_code: int | None`,
  `truncated: bool`. PRD §7.5's `{stdout, stderr, artifacts}` promises a split their protocol
  does not carry and an `artifacts` key nothing produces.

There is no bwrap-class local tier upstream. `LocalShellBackend` is documented as *"no
isolation"*; [deepagents#2882](https://github.com/langchain-ai/deepagents/issues/2882) has
requested a native local sandbox since 2026-04-22. The one package answering it,
`deepagents-sandbox` 0.0.2 (MIT), **does** implement `SandboxBackendProtocol` — via a
`langchain.py` its README never shows — but is `Development Status :: Alpha`, has two
releases both dated 2026-04-22, and its source repository `john221wick/sandy` now returns
404. A 17 KB wheel is the only surviving artifact.

### The finding that decided the probe

`deepagents-sandbox`'s `detect.py` is the auto-detect algorithm this ticket had to design,
and it **fails open**:

```python
def check_user_namespaces() -> CheckResult:
    try:
        with open("/proc/sys/kernel/unprivileged_userns_clone") as f: ...
    except FileNotFoundError:
        return CheckResult(name="user_namespaces", passed=True,   # assumes success
            reason="sysctl not present; kernel likely supports ... by default")
```

That sysctl is a **Debian/Ubuntu patch**. On mainline kernels (Fedora, Arch, RHEL 9+) the
file is absent, so the probe returns `passed=True` having verified nothing, and it never
reads mainline's actual knob, `user.max_user_namespaces`, where `0` means namespaces are
off. `check_bwrap()` is `shutil.which("bwrap")` — presence on `PATH`, not function. The
package's README says it is tested on Ubuntu 22.04 and 24.04, which is exactly the surface
where the optimistic branch never fires.

A probe that reports isolation it has not confirmed is the precise failure PRD §12 names —
*"weak isolation on subprocess fallback misunderstood as secure"* — and under
`require_isolation=True` it converts a refusal into a false pass.

## Decision

### 1. The sandbox contains programs we did not write. Three surfaces, not two

| surface | runs | containment |
| --- | --- | --- |
| hostile file bytes (Parquet) | in-process | **named gap**, its own future ticket |
| transform / `raw_sql` | in-process | ADR-0008's three locks + identifier allowlist |
| `make_chart` (generated code) | **the sandbox** | this ADR |

§7.5's rule — *"any code authored or influenced by the LLM, **and any parsing of untrusted
data content**, executes in the sandbox"* — is retired in its second half. That clause has
never been true in the built system: ADR-0011 runs the profiler in-process and writes the
hostile-Parquet vector down as accepted and unsolved rather than pretending otherwise. A
defence that is documented but not built is worse than a named gap, so the gap is named
here and gets its own ticket. **ADR-0011 and the P0 seam are not reopened.**

### 2. Planner-authored transforms stay in-process — the call ADR-0005 D6 deferred

ADR-0005 D6 ran the transform in-process at P0, said *"this is not a precedent for P1"*, and
left *"when the planner lands, planner-authored transforms route through the sandbox"* to
the rail work. **This ADR is that call, and it goes the other way: they stay in-process.**

ADR-0008 already contains model-authored SQL with three independent locks — DuckDB's own
parser as a one-`SELECT` allowlist, a relation allowlist off `json_serialize_sql`'s parse
tree, and a connection opened `enable_external_access=False` then `SET lock_configuration=true`,
measured to refuse `read_csv`, `COPY … TO`, `ATTACH` and its own unlocking. Routing the
transform through the sandbox as well would move the *source read* inside the boundary,
which Decision 5 forbids for a stronger reason than it would gain.

### 3. Our own protocol, narrow, in `__all__`; deepagents is adapted, never inherited

`chartagent.SandboxBackend` is a `typing.Protocol` of ours, and a shipped adapter wraps any
`deepagents.SandboxBackendProtocol` implementation so their six cloud providers (E2B,
Daytona, Modal, Runloop, LangSmith, Vercel) remain available without their types entering
our contract. Same posture as `Rasteriser` (ADR-0005 D9).

The measured churn is the argument, and it lands **exactly** where PRD §7.6's bridge would
have sat: `execute` held still across eleven releases while the filesystem half lost six
public methods. PRD §12 already committed to *"deepagents used at the agentic joints behind
our own thin interface"* — and a protocol in `__all__` is not a joint, it is the interface.

### 4. Lock the job, not the methods

The protocol expresses **run generated chart code on transform-output rows and return
declared artifacts**. `upload` / `run` / `download` is a remote shell: it is a superset of
what we need, it hands every implementer a filesystem to get wrong, and it is the shape
whose upstream analogue we just measured churning.

### 5. The sandbox receives transform-output rows and nothing else

The source path, the credentials and the raw bytes never enter it. `bind` runs the
transform in-process (Decision 2) and only its **output** rows cross — small by
construction, since PRD §7.3 already commits that rendering receives materialised aggregate
rows.

Refresh is the same path: `bind` re-runs the transform in-process, then the sandbox
re-calls `make_chart` on the new rows. ADR-0011's locality question — *"profiling next to
the bytes when a remote sandbox owns them"* — **does not arise**, because the sandbox never
owns the bytes. Flavour-2 pushdown sitting next to warehouse bytes, if it is ever wanted, is
a data-source decision and not a sandbox one.

This **inverts PRD §7.1**, whose headline is *"data flows only through the sandbox"*.
Erratum below. §7.1's actual principle — the LLM never touches raw data — is strengthened,
not weakened: it becomes structural rather than procedural.

### 6. Configuration on the object, execution on a session

```python
class SandboxBackend(Protocol):
    @property
    def boundary(self) -> Boundary: ...
    @property
    def runtimes(self) -> frozenset[Runtime]: ...
    def __enter__(self) -> SandboxSession: ...
    def __exit__(self, *exc: object) -> None: ...

class SandboxSession(Protocol):
    def run(self, job: ChartJob) -> ChartRun: ...
```

`create_chart_agent` holds the configured backend; `__enter__` returns a session; `run`
hangs off the session, never off the object in `__all__`. **One request's revise loop is one
`with`.** Concurrent Studio requests are concurrent sessions.

The lifecycle is the one protocol knob the revise loop earned: the review gate is a
bounded generate→critique→revise, and on a `vm` or container backend provisioning dominates
a chart render, so a protocol without lifecycle forces every implementer to invent pooling.
Runs stay mutually clean within a session — reuse buys warm infrastructure, never a shared
workspace. `run()` on the same instance a session is open on is **undefined**; that is
`deepagents-sandbox`'s persistent-`/workspace` hazard one level up.

Synchronous, like `Rasteriser`; an async sibling comes later. Timeout, pooling and every
other knob live on the configured backend's **constructor**, per ADR-0005 D9.

### 7. `runtime` is on the session, declared now at one legal value

`Runtime = Literal["python"]`, chosen at `__enter__` because the image is chosen there.
Declaring the axis with a single value costs one field and makes the `web` profile an
**additive widening** rather than a breaking change to a published `Protocol` — the move
ADR-0009 made with `chartType` as a generated `Literal` whose count is deliberately
unfrozen. A python-only backend asked for `web` is **unsupported, not a crash** (the
`Rasteriser` / Excel posture).

> **Erratum — 2026-08-28 ([#57](https://github.com/thearcscode/chartagent/issues/57),
> [ADR-0017](0017-the-custom-rail-produces-an-interactive-web-document.md)). The phase ordering
> here is reversed.** The **web** profile is the phase-P2 custom rail, and **python** is the
> later widening — not the other way round. The custom rail produces an interactive web
> document, which runs in a sandboxed iframe (Studio) and in the `Rasteriser`'s browser
> (review), so **phase P2 does not implement `SandboxBackend` at all**: no python extra, no
> bwrap probe, no `[docker]` work.
>
> **This ADR remains Accepted, as the contract for the python widening.** Decision 1's rule —
> the sandbox contains programs we did not write — is unchanged and now has **two
> implementations**, of which only the client-side iframe is on the P2 path.
>
> **Decisions 9 and 10, and their errata below, are re-scoped**: they describe the **python
> widening**, not phase P2. `[#6](https://github.com/thearcscode/chartagent/issues/6)` is not
> reopened.

### 8. Rows cross as a `pyarrow.Table`; the runner hands `make_chart` an Arrow-backed DataFrame

`ChartJob` carries a **`pyarrow.Table`** (pyarrow is already base, #19). Arrow IPC is how it
crosses the process wall, through our helper — **callers never write IPC bytes**.

Arrow because it is the only candidate that preserves types exactly: CSV would round-trip a
`TIMESTAMPTZ` into a string, and ADR-0010 exists precisely because a retype that looks
cosmetic moves bars on the chart. A pandas `DataFrame` at the callsite because the codegen
bias rests on measured library familiarity (1.8% incorrect for Matplotlib vs 22% for Plotly,
PandasPlotBench) and matplotlib code is *written* against DataFrames.

**The DataFrame is Arrow-backed** — `Table.to_pandas` with Arrow dtypes, UTC pinned per
ADR-0008 D9. Default NumPy `to_pandas` is the type-lossy step that would undo the reason
Arrow was chosen.

### 9. The charting stack is the image's, not the wheel's

pandas and matplotlib are **not** in the base wheel (#19 D4 / D9). #19's *"bwrap and
subprocess need nothing extra"* is about **isolation tools**, not the charting stack.

- **subprocess has no image**, so a **host extra** is its image, and a missing extra is
  `SandboxUnavailableError(kind="backend_missing")` naming it, per #19.
- **`os` and `vm` backends bake the same stack into the image.**
- **Nothing goes on `[docker]`.**

**Erratum — 2026-08-28 ([#55](https://github.com/thearcscode/chartagent/issues/55),
ADR-0016).** The stack is **pandas, matplotlib, seaborn and numpy** — seaborn because
ADR-0016 Decision 1 closes the rail on the `matplotlib.figure.Figure` return type rather than
on an import name, and numpy because Decision 11 seeds it. Both are still **not** in the base
wheel and still **not** on `[docker]`; the rule above is unchanged, only its list.

### 10. Artifacts come back as bytes; the runner is ours; the model never names a path

```python
ChartRun.artifacts: Mapping[Format, bytes]
```

One round trip, `Rasteriser`'s shape — charts are small by construction. Generated code is
shaped `def make_chart(data) -> Figure`; **we inject the runner** that calls it and
serialises the return, so the job *requests formats* and the model neither declares nor
names an artifact. A model that writes `plt.savefig("/tmp/…")` gets nothing: the only bytes
that leave are the ones our runner serialised.

Two locks:

1. **The runner is ours.** Third-party backends run the payload we hand them; they do not
   reimplement `Figure` serialisation. A deepagents adapter may use `execute` internally —
   that is not our public verb.
2. **`figure_json` is how the data-truthfulness check reads numbers** (PRD §7.3), so
   requesting it is not optional for a reviewed chart. Returned artifact bytes are
   **capped**, the numeric limit being configuration like `bind`'s timeout, so a hostile
   `make_chart` cannot push gigabytes into the parent process.

Runner v1 serialises `matplotlib.figure.Figure`. plotly and bokeh stay legal on this
runtime; their serialisation is a runner widening owned by the custom-rail ticket — not a
protocol change.

**Erratum — 2026-08-28 ([#55](https://github.com/thearcscode/chartagent/issues/55),
ADR-0016).** *"plotly and bokeh stay legal on this runtime"* is **withdrawn**. If the runner
cannot serialise them, a chart written in them cannot come back, so "legal" was a hard
constraint wearing a soft word. The **runtime** is still `python`; the **runner is
`matplotlib.figure.Figure`-only**, which admits seaborn (its figures are matplotlib's) and
excludes plotly and bokeh until a widening — a widening that needs a `figure_json` extraction
per library, not an import-list edit. ADR-0016 Decision 1.

**Second erratum, same date and ticket.** The implication that closing the library question
settles `figure_json`'s **shape** is wrong: it settles its **owner**. Matplotlib ships no
figure→JSON API and [MEP25](https://matplotlib.org/stable/devel/MEP/MEP25.html) — which would
have added one — is **Status: Rejected**, *"this particular effort has stalled"*. So
`figure_json` is ours to define, extraction is **per-artist**, and its coverage is per-artist
type: ADR-0016 Decision 9 fixes the v1 set as `Line2D`, bar `Rectangle`s and
`PathCollection`, with anything outside it reported as *not checked* rather than passed or
failed.

Writing declared artifacts into the deepagents VFS (PRD §7.6) stays true, but as the **agent
layer's** job one level above this protocol. Putting it *in* the protocol was refused
hardest of the three options, because it is exactly the surface measured churning.

### 11. Isolation is a boundary kind, not a tier number

`Boundary = Literal["none", "os", "vm"]`, a public property set at construction.

PRD §7.5's four-tier table implies a total order, subprocess < bwrap < docker < e2b, and
that order is not sound: bwrap and docker are both kernel-sharing namespace isolation, and a
tight bwrap profile with `--unshare-net` is arguably stronger than a default `docker run`,
which attaches a bridge network and runs as root in-container unless configured otherwise.
Only Firecracker-class virtualisation is a categorically different wall.

Three values are also the only form a third-party implementer can answer **honestly**: a
tier number invites inflation, and a capability set invites us to publish claims about other
people's backends we cannot verify. The docs matrix then says something true — the promise
is *"you are not on a bare subprocess"*, not *"rung 3 of 4"*.

A third party can still lie about its kind. **We accept that.** An adapter over
`LocalShellBackend` declares `none`.

### 12. The boundary is the wall, not the rlimits

Missing cgroup v2 does **not** make bwrap into `none` if namespaces actually work.
`require_isolation` does not mean *"has memory limits"*. Resource caps stay on the
constructor. The probe may log cgroup v2 availability; it must not fold it into the kind.

### 13. `require_isolation=True` means "not `none`", and raises at construction

It raises rather than falling back, and the error names the boundary found against the
boundary required.

### 14. The probe executes; it never infers from `PATH`

`sandbox="local"` resolves by **running** `bwrap --unshare-all --ro-bind / / true` and
checking the exit code. The answer is *"bwrap works here"*, never *"bwrap is on `PATH` and a
Debian sysctl was missing"*. `deepagents-sandbox`'s fail-open branch is the anti-pattern,
read from the 0.0.2 wheel and reproduced in *Context* so the reason survives the decision.

### 15. Probe once at construction; the verdict is immutable; never silently demote

The probe runs at backend construction and its verdict is fixed for that instance's life,
which is what makes both the log line and `require_isolation` deterministic, and puts the
resolution of `sandbox="local"` where ADR-0005 D9 already puts every knob.

Per-process memoisation is **rejected**: Studio will hold more than one configured backend
in one process. Re-probing per run is rejected for a worse reason — a fork refused under
memory pressure would silently demote `os` to `none` mid-flight, invisibly when
`require_isolation` is `False`.

**Never silently demote.** If construction resolved `os` and bwrap later fails to start,
that is `SandboxUnavailableError(kind="provision_failed")`, not a fallback to `none`.
Fallback to `none` exists **only** for `sandbox="local"`, and **only** at construction.
Explicit `"bwrap"` / `"docker"` never falls back.

### 16. One log line at construction, and a public `boundary`

`backend.boundary` is public and Studio reads it. On top of that, **exactly one** log record
at construction naming implementation and boundary: `logging.warning` when the boundary is
`none`, `logging.info` otherwise.

Not silent on `os`. Not per-run — a configuration fact repeated per chart trains operators
to filter it. Not `warnings.warn`, and **not an `Advisory`**: ADR-0005 reserved advisories
for something the library did or ignored *on that bind*, and this is a configuration fact,
not a call-site one.

### 17. Two errors, split by raise site, each carrying a `kind`

```python
class SandboxUnavailableError(ChartAgentError):   # before generated code runs
    kind: Literal["backend_missing", "runtime_unsupported", "isolation_unmet", "provision_failed"]

class SandboxExecutionError(ChartAgentError):     # run()
    kind: Literal["code_raised", "timeout", "artifact_too_large"]
```

The split is what a caller's `except` actually wants — *"I misconfigured this"* against
*"the model wrote bad code"*. `kind` follows the house pattern already set by
`SchemaDriftError.stage`, `RawSqlRejectedError.reason`, `SpecVocabularyError.kind` and
`BackendCapabilityError.kind`.

Raise sites: `isolation_unmet` and `backend_missing` at **construction**;
`runtime_unsupported` and `provision_failed` at **`__enter__`**; the execution kinds at
`run()`.

**No `IsolationUnavailableError`.** A separate name was considered for loudness and
rejected: loudness is `kind="isolation_unmet"` plus Decision 16's warning, and the house
style is one error with a `kind`, not a family of names.

### 18. What `__all__` gains

`SandboxBackend`, `SandboxSession`, `ChartJob`, `ChartRun`, `Boundary`, `Runtime`,
`SandboxUnavailableError`, `SandboxExecutionError`. The module is `sandbox/`, already named
by #19's layout for this ticket.

## What this amends

- **ADR-0005 Decision 6** — *"when the planner lands, planner-authored transforms route
  through the sandbox; that is the rail work's call"*. Dated erratum: this ADR is that call,
  and they **stay in-process**, contained by ADR-0008's three locks. The P0 posture is
  unchanged; what changes is that it is no longer provisional.
- **PRD §7.1** — *"data flows only through the sandbox"* is inverted by Decision 5. Data
  flows through `bind`, in-process; only transform **output** reaches the sandbox.
- **PRD §7.5** — the untrusted-data clause is retired (Decision 1); the protocol shape is
  replaced (Decisions 4, 6, 10); the four-tier table becomes three boundary kinds
  (Decision 11); auto-detect is specified (Decisions 14, 15).
- **PRD §7.6** — the bridge is the agent layer's job, not this protocol's (Decision 10), and
  the source file does not live on the sandbox disk (Decision 5).
- **PRD §9 P0.6** and **§13's "Local sandbox default" row** — tier numbers replaced by
  boundary kinds; the acceptance criterion becomes *the probe executed and the boundary is
  not `none`*.

## Consequences

- **The sandbox is smaller than the PRD describes, and honest about it.** One job, one verb,
  one lifecycle. The hostile-data vector is a named gap with its own ticket rather than a
  promise this protocol silently fails to keep.
- **A remote tier is cheap by construction.** Because only aggregate rows cross, "self-hostable
  sandbox" never quietly means "your warehouse rows go to a third party".
- **We own a bwrap backend.** Taking a runtime dependency on an alpha package with two
  same-day releases, four months idle and a vanished source repository — in the one component
  whose entire job is to *be* a security boundary — is the dependency not to take. Its
  cgroup-v2 handling and four-check skeleton are worth lifting under MIT, with credit; its
  `detect.py` is not.
- **pandas and matplotlib move into images and a host extra**, so the base wheel #19 froze is
  unchanged.
- **A third party can misdeclare its boundary.** Accepted and recorded; structural typing
  cannot verify a security claim.

## Alternatives rejected

- **Adopt `deepagents.SandboxBackendProtocol` as ours** — Decision 3. Six providers for free,
  but it puts a pre-1.0 type into a contract ADR-0005 freezes, and the measured churn is in
  the half PRD §7.6 would have leaned on.
- **`upload` / `run` / `download`** — Decision 4. A remote shell, and its upstream analogue
  promises a stdout/stderr split `ExecuteResponse` does not carry.
- **Artifacts into the deepagents VFS** — Decision 10. Refused hardest of the three return
  paths, for the same churn reason.
- **The four-tier ordered ladder** — Decision 11. bwrap-versus-docker is not a sound ordering.
- **A capability set (`network`, `filesystem`, `pids`, `memory`)** — Decision 11. Honest in
  principle, but it makes us publish verifiable-sounding claims about other people's backends.
- **Depending on `deepagents-sandbox`** — Consequences above.
- **`IsolationUnavailableError` as its own name** — Decision 17.
- **Per-process probe memoisation, and per-run re-probing** — Decision 15.

## What this feeds

- **Custom-rail codegen design** (fog) inherits the `make_chart(data)` contract with `data`
  now fixed as an Arrow-backed `DataFrame`, the runner's v1 `Figure` serialisation and the
  widening path for plotly/bokeh, and the fact that `figure_json` is mandatory for a
  reviewed chart.
- **Review-gate tier design** (fog) inherits `figure_json` as the truthfulness check's input
  and the rule that a chart failing review stays on its rail (ADR-0013).
- **The hostile-data gap** is a named, unsolved vector needing its own ticket — not minted
  from this session.
- **The `web` runtime profile** is Fast follows: `Runtime` widens additively, and the Node
  image's shape is not this ADR's.

## Related

- `deepagents` 0.7.10 `backends/protocol.py`; docs `oss/python/deepagents/{backends,sandboxes}.mdx`
- [deepagents#2882](https://github.com/langchain-ai/deepagents/issues/2882) — native local
  sandbox backend, open since 2026-04-22
- `deepagents-sandbox` 0.0.2 (MIT) — bubblewrap + cgroups v2; source repository unavailable
- PRD §7.1, §7.3, §7.5, §7.6, §9 P0.6, §11, §12, §13
