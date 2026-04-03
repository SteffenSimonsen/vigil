# The Columbo Pattern — Fuzzy Bug Finding with Autonomous Agents

> A design exploration: using an unsupervised detective agent for QA, and the open problems that surface when you try to make it autonomous.

---

## Origin: The Prompt

The idea came from a single observation: most automated QA is confirmatory. It checks things the author expected to check. The Columbo Pattern inverts that — it assumes something is wrong and tries to create the conditions under which bugs reveal themselves.

The original prompt brief:

> You are a detective, not a builder. Your job is to poke, probe, and question the codebase from unexpected angles. Assume something is wrong and your task is to find it.
>
> Run commands nobody asked you to run. Try the build in ways the author didn't test. Call functions with edge-case inputs. Check what happens when config is missing, when permissions are wrong, when dependencies are out of date. Follow hunches. Circle back to things that felt odd.
>
> You are not looking for a specific bug. You are creating the conditions under which bugs reveal themselves. Each probe is cheap. Most will find nothing. The ones that don't find nothing are the entire point.
>
> When something breaks, cracks, or behaves unexpectedly — document it precisely: what you tried, what you expected, what actually happened. Then keep going. Don't fix. Don't judge. Just keep asking "one more thing."

The key constraints: no fixing, no judging, just probing. The detective metaphor is load-bearing — it licenses the agent to follow hunches and circle back, rather than executing a checklist.

---

## What the Agent Actually Found

A single blind pass against the vigil codebase. 30+ probes. 12 confirmed bugs, filed as issues #22–#33.

### High severity

**#22 — Empty command crashes with IndexError**
`vigil start "name" ""` — `shlex.split("")` returns `[]`, `IndexError` escapes the `except (FileNotFoundError, PermissionError, ValueError)` handler. Same crash with whitespace-only commands.

**#23 — `--json` flag violated on Vigilfile errors in `up`/`down`**
`vigil up --json` with no Vigilfile emits plain-text to stdout. The `VigilfileParseError` handler fires before the `--json` check — machine consumers get unparseable output.

**#24 — Path traversal via process names with `/` or `..`**
`vigil start "../../../tmp/evil" "sleep 300"` was accepted. `open_log()` calls `log_path.parent.mkdir(parents=True, exist_ok=True)` — writing log files to arbitrary filesystem locations. **Confirmed on disk**: `/tmp/tmp/evil.log` was created outside the `.vigil/` directory.

### Medium severity

**#25 — Empty string name accepted on start but unstoppable**
`vigil start "" "sleep 300"` succeeds. `vigil stop ""` hits an `if not name:` falsy check and refuses. The only escape is `vigil stop --all`.

**#26 — Corrupted state.json causes raw tracebacks on all commands**
`JSONDecodeError`, `KeyError`, and `PermissionError` all escape to top-level tracebacks. No graceful degradation, no JSON output.

**#27 — `vigil open` returns `http://localhost:None`**
When a process has no port and live detection finds nothing, the code falls through to `f"http://localhost:{record.port}"` with `port = None`.

**#28 — `httpx.InvalidURL` not caught in health/wait**
`vigil health --endpoint "no-slash"` constructs `http://localhost:8080no-slash` — `httpx.InvalidURL` is not a subclass of `httpx.RequestError` and escapes the `except` block. Same bug in `wait.py`.

### Low severity

**#29 — `vigil next` returns ports above 65535**
No upper bound validation. `vigil next 99999` returns `{"port": 99999}`.

**#30 — `vigil up` exits 0 when all processes fail**
JSON contains `"status": "failed"` entries but the process exit code is 0. Shell callers using `&&` don't detect the failure.

**#31 — `vigil init --process "name"` silently creates broken Vigilfile**
Spec with no command component writes `command = ""`. Subsequent `vigil up` hits the IndexError from #22.

**#32 — Long process names cause unhandled OSError**
10,000-char name → `OSError: [Errno 36] File name too long` from deep inside `open_log()`. No validation at registration time.

**#33 — Concurrent `vigil stop` has a read-modify-write race**
Atomic rename protects against partial writes but not lost-update races. Under concurrent load, one stop's write can overwrite another's deletion, leaving stale state entries.

### The value of the findings

The hit rate was high for a single unsupervised pass. More importantly, the *character* of the findings was different from what tests typically surface — they were found by approaching the CLI in ways the author hadn't tested: adversarial names, concurrent invocations, broken state files, out-of-range inputs. The path traversal (#24) in particular came from a hunch, not a category in the prompt.

---

## Pain Points

### Visibility: being in the dark

The agent ran for ~30 minutes with no external signal. From the outside it was impossible to tell whether it was making progress, stuck in a loop, or nearly done. The experience was: "thinking the agent would never stop."

This is the core UX problem with unsupervised roaming agents. The value of the findings comes precisely from the unguided exploration, but unguided exploration looks identical to being stuck.

### Termination: no forcing function

The prompt said "at least 25-30 probes" — a floor, not a ceiling. "Keep asking one more thing" is great detective flavour but a bad termination condition. Without a hard budget the agent has no natural stopping point.

---

## Brainstorm: Signal Quality for Autonomous Operation

### The visibility fix is not just a UX fix

Better visibility (a heartbeat, probe-by-probe progress) would make the human more comfortable watching. But the deeper problem is that better signal enables autonomous operation — other agents acting on findings without a human in the loop at all.

Today the chain is: Columbo finds → human reads → human files issues → Ralph fixes. The human is doing interpretation and routing. If findings are structured and machine-readable, that middle step collapses.

### Signal has two dimensions

**Structure** — findings need to be typed, not prose. Not just "here is a finding" but: area probed, bug class, severity, exact reproduction steps. Enough for a downstream agent to route without understanding.

**Timing** — signal should arrive *during* the run, not at the end. A stream of probe events (`{probe, result: clean|finding}`) lets an orchestrator make decisions in flight.

### What high-quality signal unlocks

- **Density routing**: findings clustering in one subsystem tell an orchestrator to spawn a deeper focused pass there while the broad pass continues elsewhere.
- **Novelty detection**: is this a new bug class or the 4th variant of the same missing-validation pattern? Determines whether to dig or move on.
- **Coverage tracking**: which areas have been probed clean — prevents redundant work across runs.
- **Direct Ralph integration**: structured findings flow straight into the fix queue, triaged by severity, without human filing.

### The structure trap

Imposing structure on Columbo directly — requiring him to emit typed JSON per probe — is dangerous. It forces him to work within a predefined taxonomy. That taxonomy will miss the things that don't fit categories, which are often the most interesting findings.

The solution: keep the agent loose, add a **translation layer** after the run. A lightweight agent that reads freeform findings and structures them. The detective stays uncontaminated; the pipeline gets the grip it needs.

---

## The Roaming Quality Duality

The core tension: tighter scaffolding → better UX, worse findings. Looser scaffolding → better findings, human sits in the dark.

But total unsupervised freedom isn't actually where roaming quality peaks — it's where *uniform* roaming happens. The agent probes with equal enthusiasm everywhere. It has no feel for "this area smells interesting" vs "this is noise." Dead ends get the same investment as real finds.

Columbo himself doesn't work this way. He's seen hundreds of cases. When something feels off it's because it doesn't match his internal model. He *knows* when a thread is cold and pivots. The agent version starts from zero every run — no accumulated sense of where this codebase tends to fail.

**The dead-end problem and the signal quality problem are the same problem.** If the agent emitted structured dead ends alongside findings — "probed X, found nothing, low value area" — that becomes the substrate for the next run. The second run isn't starting from scratch.

Roaming quality is highest not when the agent is totally unsupervised, but when it's **unsupervised within a space shaped by prior runs**. That's actually closer to how Columbo works too.

---

## The Graph-Based Memory Avenue

### Why a graph, not a list

A flat finding list tells you *what* was found. A graph tells you the *relationships* — which areas are connected, where findings clustered, which probes were adjacent to findings without being findings themselves. That adjacency is where instinct lives.

### Node and edge schema (sketch)

**Nodes**: subsystems, bug classes, probe types, CLI commands, code paths, invariants.

**Edges**: weighted by probe history. How often has a probe in area X led to a finding? How often has bug class Y appeared near subsystem Z?

Over multiple runs the graph develops topology reflecting the actual fault distribution of the codebase.

### What Columbo does with it

At the start of a run he consults the graph — not to be told what to do, but to know where terrain is already mapped. He can still roam freely, but gravitates toward high-weight edges and unexplored nodes. Cold terrain he's already covered gets less attention; warm terrain adjacent to past findings gets more.

After the run he writes back — updating edge weights, adding nodes for novel bug classes, marking dead ends as low-value. The graph gets smarter with each run.

### The graph as a QA map

Beyond steering Columbo, the graph is independently useful. Its topology answers questions directly: where is this codebase most fragile? Which bug class keeps recurring? What areas have never been probed? It becomes a living QA map of the codebase — readable by humans and agents alike.

### The hard design problem: node identity

What counts as "the same area" across runs when code changes? If `cli.py` gets refactored, nodes that reference it need to migrate gracefully or the memory degrades.

The principle: anchor nodes to **stable concepts** — bug classes, interface boundaries, invariants — rather than file paths or function names. File paths are implementation details. The invariant "all `--json` paths emit valid JSON" is stable across refactors.

Get the node schema right and the rest follows.

---

## Where This Goes

The Columbo Pattern is good backpressure in a QA feedback loop. The current one-shot form is already valuable. The path to autonomous operation runs through:

1. **Structured streaming output** — findings emitted during the run, typed and machine-readable, via a translation layer that doesn't constrain the agent itself.
2. **Graph-based codebase memory** — accumulated probe history that shapes where Columbo pays attention without removing his freedom to roam.
3. **Orchestration layer** — reads the signal stream, spawns focused follow-up passes where findings cluster, routes confirmed findings to Ralph without human intervention.

The human's role shifts from "watching the agent and filing issues" to "reviewing the graph and deciding what new invariants to encode."
