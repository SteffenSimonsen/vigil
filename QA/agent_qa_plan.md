# Vigil QA Execution Plan

## Instructions for the agent

Execute every test in order. For each test record:
- The actual command output
- PASS or FAIL
- Any NOTE if behaviour is surprising but not clearly wrong

At the end, return a summary table listing every test ID, its result, and any notes.

`vigil` is already installed and available in PATH.

---

## Setup

Run once before all tests:

```bash
rm -rf /tmp/vigil-qa
mkdir /tmp/vigil-qa
cd /tmp/vigil-qa
vigil init --process "web,python3 -m http.server 18765,18765" --json
```

All subsequent commands are run from `/tmp/vigil-qa` unless stated otherwise.
Ports used: 18765–18773 (high range to avoid conflicts with system services).

---

## Section 1 — Init

**T01** — Init already exists is rejected
```bash
vigil init --process "web,python3 -m http.server 18765,18765" --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T02** — Init --force overwrites
```bash
vigil init --process "web,python3 -m http.server 18765,18765" --force --json
echo "exit:$?"
```
PASS if: JSON contains `"status": "created"`, exit code is 0.

**T03** — Init rejects empty command
```bash
vigil init --process "web," --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T04** — No project error (run from a directory with no .vigil/)
```bash
cd /tmp && vigil status --json
echo "exit:$?"
cd /tmp/vigil-qa
```
PASS if: output mentions `vigil init`, exit code is 1.

---

## Section 2 — Start / Status

**T05** — Start a process
```bash
vigil start web "python3 -m http.server 18765" --json
echo "exit:$?"
```
PASS if: JSON has `"status": "started"` and a numeric `"pid"`, exit code is 0.

**T06** — Status shows process alive (run ~1 second after T05)
```bash
sleep 1 && vigil status --json
```
PASS if: `managed` array has one entry with `"alive": true` and `"ports"` containing 18765.

**T07** — Human-readable status
```bash
vigil status
```
PASS if: output contains `● alive` and `18765`.

**T08** — Start duplicate without --force is rejected
```bash
vigil start web "python3 -m http.server 18765" --json
echo "exit:$?"
```
PASS if: JSON contains `"error"` mentioning already running, exit code is 1.

**T09** — Start with --force replaces the process
```bash
OLD_PID=$(vigil status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['managed'][0]['pid'])")
vigil start web "python3 -m http.server 18765" --force --json
echo "exit:$?"
```
PASS if: JSON has `"status": "started"` with a PID different from `$OLD_PID`.

**T10** — Start rejects empty name
```bash
vigil start "" "python3 -m http.server 18765" --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T11** — Start with --env injects variable
```bash
vigil start env-test "env" --env VIGIL_QA=hello --json
sleep 1
vigil logs env-test | grep VIGIL_QA
```
PASS if: `grep` finds `VIGIL_QA=hello` in the log output.

**T12** — Start with --cwd sets working directory
```bash
mkdir -p /tmp/vigil-qa/subdir
vigil start cwd-test "pwd" --cwd /tmp/vigil-qa/subdir --json
sleep 1
vigil logs cwd-test
```
PASS if: log output contains `/tmp/vigil-qa/subdir`.

---

## Section 3 — Wait

**T13** — Wait returns ready for a running process
```bash
vigil wait web --timeout 10 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "ready"`, exit code is 0.

**T14** — Wait with --port
```bash
vigil wait web --port 18765 --timeout 5 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "ready"`, exit code is 0.

**T15** — Wait with --http (any HTTP response counts)
```bash
vigil wait web --http --timeout 10 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "ready"`, exit code is 0.

**T16** — Wait with --http=/path (404 still counts as ready)
```bash
vigil wait web --http=/no-such-path --timeout 5 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "ready"`, exit code is 0.

**T17** — Wait timeout when port never opens
```bash
vigil start slow "sleep 60" --json
vigil wait slow --port 19999 --timeout 2 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "timeout"`, exit code is 1.

**T18** — Wait detects process death (exit code 2)
```bash
vigil start dying "sleep 0.1" --json
sleep 1
vigil wait dying --timeout 5 --json
echo "exit:$?"
```
PASS if: JSON has `"status": "died"`, exit code is 2.

**T19** — Wait on unknown name
```bash
vigil wait nobody --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

---

## Section 4 — Logs

**T20** — Tail logs (human)
```bash
vigil logs web --tail 5
```
PASS if: output is non-empty (any log lines from the http.server).

**T21** — Logs as JSON
```bash
vigil logs web --tail 3 --json
```
PASS if: JSON has a `"lines"` array with up to 3 strings.

**T22** — Logs for unknown process
```bash
vigil logs nobody --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T23** — Log file exists at expected path
```bash
ls /tmp/vigil-qa/.vigil/logs/web.log
echo "exit:$?"
```
PASS if: file exists, exit code is 0.

---

## Section 5 — Stop

**T24** — Stop a live process
```bash
vigil stop web --json
echo "exit:$?"
```
PASS if: JSON has `"status": "stopped"`, exit code is 0.

**T25** — Stopped process absent from status
```bash
vigil status --json
```
PASS if: `managed` array does not contain an entry named `web`.

**T26** — Log is trimmed after stop (≤ 500 lines)
```bash
wc -l /tmp/vigil-qa/.vigil/logs/web.log
```
PASS if: line count is ≤ 500.

**T27** — Stop unknown process
```bash
vigil stop nobody --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T28** — Stop a crashed process cleans up statefile
```bash
vigil start crash-test "sleep 60" --json
CPID=$(vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='crash-test']")
kill $CPID
sleep 1
vigil stop crash-test --json
echo "exit:$?"
vigil status --json | python3 -c "import sys,json; names=[p['name'] for p in json.load(sys.stdin)['managed']]; print('absent' if 'crash-test' not in names else 'present')"
```
PASS if: stop exits 0 and the final python3 call prints `absent`.

**T29** — Stop --all
```bash
vigil start aa "sleep 60" --json
vigil start bb "sleep 60" --json
vigil stop --all --json
echo "exit:$?"
vigil status --json
```
PASS if: stop exits 0 and subsequent status shows an empty `managed` array (or only crashed entries that are legitimately still there from earlier tests — verify aa and bb are gone).

---

## Section 6 — Restart

**T30** — Restart produces a new PID
```bash
vigil start web "python3 -m http.server 18765" --json
OLD=$(vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='web']")
vigil restart web --json
echo "exit:$?"
NEW=$(vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='web']")
python3 -c "print('different' if '$OLD' != '$NEW' else 'same')"
```
PASS if: JSON has `"status": "restarted"`, exit code is 0, and PIDs are `different`.

**T31** — Restart unknown process
```bash
vigil restart nobody --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

---

## Section 7 — Remove

**T32** — Remove a crashed entry
```bash
vigil start toremove "sleep 60" --json
RPID=$(vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='toremove']")
kill $RPID
sleep 1
vigil remove toremove --json
echo "exit:$?"
```
PASS if: JSON has `"status": "removed"`, exit code is 0.

**T33** — Remove alive process without --force is rejected
```bash
vigil start keepalive "sleep 60" --json
vigil remove keepalive --json
echo "exit:$?"
```
PASS if: JSON contains `"error"` mentioning alive or running, exit code is 1.

**T34** — Remove alive process with --force
```bash
vigil remove keepalive --force --json
echo "exit:$?"
vigil status --json | python3 -c "import sys,json; names=[p['name'] for p in json.load(sys.stdin)['managed']]; print('absent' if 'keepalive' not in names else 'present')"
```
PASS if: exit code is 0 and python3 prints `absent`.

---

## Section 8 — Scan

**T35** — Default scan finds managed process port
```bash
vigil start scan-svc "python3 -m http.server 18766" --json
sleep 1
vigil scan --json | python3 -c "import sys,json; ports=[l['port'] for l in json.load(sys.stdin)['listeners']]; print('found' if 18766 in ports else 'missing')"
```
PASS if: prints `found`.

**T36** — Scan --port returns exactly one entry
```bash
vigil scan --port 18766 --json
```
PASS if: `listeners` array has exactly one entry with `"port": 18766`.

**T37** — Scan --range returns ports within range
```bash
vigil scan --range 18760-18770 --json
```
PASS if: all returned entries have ports between 18760 and 18770 inclusive, and 18766 is present.

**T38** — Scan empty port returns empty list
```bash
vigil scan --port 19998 --json
```
PASS if: `"listeners": []`.

**T39** — Scan --all returns more listeners than default
```bash
DEFAULT=$(vigil scan --json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['listeners']))")
ALL=$(vigil scan --all --json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['listeners']))")
python3 -c "print('more' if $ALL >= $DEFAULT else 'not-more')"
```
PASS if: prints `more` (or `not-more` is acceptable if no system ports are active — note it either way).

---

## Section 9 — Next

**T40** — Default next returns a port ≥ 3000
```bash
vigil next --json
```
PASS if: JSON has `"port"` with a value ≥ 3000.

**T41** — Next from occupied port skips it
```bash
vigil next 18766 --json
```
PASS if: JSON has `"port"` with a value > 18766 (18766 is occupied by scan-svc).

**T42** — Next --count 3 returns 3 consecutive free ports
```bash
vigil next 19000 --count 3 --json
```
PASS if: JSON has `"ports"` array of 3 integers all ≥ 19000, each one greater than the last.

**T43** — Next rejects start above 65535
```bash
vigil next 65536 --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

---

## Section 10 — Health

**T44** — Health reports healthy for HTTP process
```bash
vigil health --json
```
PASS if: `processes` array contains an entry for `web` (or any alive HTTP process) with `"healthy": true` and a numeric `"latency_ms"`.

**T45** — Health with custom endpoint (404 still healthy)
```bash
vigil health --endpoint /no-such-path --json
```
PASS if: same alive processes as T44 still show `"healthy": true`.

**T46** — Health only checks alive processes
```bash
vigil start tcp-only "sleep 60" --json
sleep 1
vigil health --json | python3 -c "import sys,json; names=[p['name'] for p in json.load(sys.stdin)['processes']]; print('present' if 'tcp-only' in names else 'absent')"
```
PASS if: prints `present` with `"healthy": true` and `"status": "no-port"` (process has no listening port).

---

## Section 11 — Free

**T47** — Free an unmanaged port
```bash
python3 -m http.server 18768 &
sleep 0.5
vigil free 18768 --json
echo "exit:$?"
```
PASS if: JSON has `"freed": true` and `"was": "unmanaged"`, exit code is 0.

**T48** — Free a managed port stops and removes the process
```bash
vigil start free-svc "python3 -m http.server 18769" --json
sleep 1
vigil free 18769 --json
echo "exit:$?"
vigil status --json | python3 -c "import sys,json; names=[p['name'] for p in json.load(sys.stdin)['managed'] if p['alive']]; print('absent' if 'free-svc' not in names else 'present')"
```
PASS if: JSON has `"was": "managed"`, exit code is 0, and process is `absent` from alive entries.

**T49** — Free an already-free port is idempotent
```bash
vigil free 19997 --json
echo "exit:$?"
```
PASS if: JSON has `"freed": true` and `"was": "free"`, exit code is 0.

---

## Section 12 — Open

**T50** — Open by port number returns URL
```bash
vigil open 18765 --json
echo "exit:$?"
```
PASS if: JSON has `"url": "http://localhost:18765"`, exit code is 0.

**T51** — Open by process name returns URL
```bash
vigil open web --json
echo "exit:$?"
```
PASS if: JSON has `"url"` containing `18765`, exit code is 0.

**T52** — Open unknown name is rejected
```bash
vigil open nobody --json
echo "exit:$?"
```
PASS if: JSON contains `"error"`, exit code is 1.

**T53** — Open with Vigilfile url override
```bash
printf '[[process]]\nname = "web"\ncommand = "python3 -m http.server 18765"\nport = 18765\nurl = "http://localhost:18765/custom/"\n' > /tmp/vigil-qa/Vigilfile
vigil open web --json
```
PASS if: JSON has `"url": "http://localhost:18765/custom/"`.

---

## Section 13 — Up / Down

**T54** — Setup: write a two-process Vigilfile
```bash
printf '[[process]]\nname = "svc-a"\ncommand = "python3 -m http.server 18771"\nport = 18771\norder = 1\n\n[[process]]\nname = "svc-b"\ncommand = "python3 -m http.server 18772"\nport = 18772\norder = 2\n' > /tmp/vigil-qa/Vigilfile
cat /tmp/vigil-qa/Vigilfile
```
PASS if: Vigilfile contains two `[[process]]` entries for svc-a and svc-b.

**T55** — vigil up starts all processes
```bash
vigil stop --all --json
vigil up --json
echo "exit:$?"
```
PASS if: both svc-a and svc-b have `"status": "started"`, exit code is 0.

**T56** — vigil up is idempotent (already running → skipped)
```bash
vigil up --json
echo "exit:$?"
```
PASS if: both svc-a and svc-b have `"status": "skipped"`, exit code is 0.

**T57** — vigil up --force restarts running processes
```bash
vigil up --force --json
echo "exit:$?"
```
PASS if: both svc-a and svc-b have `"status": "started"` with new PIDs, exit code is 0.

**T58** — vigil up --only starts only the named process
```bash
vigil stop svc-a --json
vigil up --only svc-a --json
echo "exit:$?"
vigil status --json | python3 -c "import sys,json; m={p['name']:p['alive'] for p in json.load(sys.stdin)['managed']}; print('a-alive:', m.get('svc-a'), 'b-alive:', m.get('svc-b'))"
```
PASS if: svc-a is alive, svc-b is alive (unchanged), exit code is 0.

**T59** — vigil down stops in reverse order
```bash
vigil down --json
echo "exit:$?"
```
PASS if: exit code is 0, and in the `processes` array svc-b appears before svc-a (reverse of startup order).

**T60** — vigil up with a failing process exits 2
```bash
printf '[[process]]\nname = "good"\ncommand = "python3 -m http.server 18773"\nport = 18773\norder = 1\n\n[[process]]\nname = "bad"\ncommand = "this-command-does-not-exist"\norder = 2\n' > /tmp/vigil-qa/Vigilfile
vigil up --json
echo "exit:$?"
```
PASS if: `good` has `"status": "started"`, `bad` has `"status": "failed"`, exit code is 2.

---

## Section 14 — JSON error format

**T61** — Errors go to stdout (not stderr) in --json mode
```bash
vigil stop nobody --json > /tmp/vigil-qa-out.txt 2>/tmp/vigil-qa-err.txt
echo "stdout:$(cat /tmp/vigil-qa-out.txt)"
echo "stderr:$(cat /tmp/vigil-qa-err.txt)"
```
PASS if: stdout contains `{"error": ...}` and stderr is empty.

---

## Section 15 — State file integrity

**T62** — State file is valid JSON
```bash
python3 -c "import json; json.load(open('/tmp/vigil-qa/.vigil/state.json')); print('valid')"
```
PASS if: prints `valid`.

**T63** — Externally killed process shows as crashed (not silently removed)
```bash
vigil start stale-test "sleep 60" --json
SPID=$(vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='stale-test']")
kill $SPID
sleep 1
vigil status --json | python3 -c "import sys,json; m={p['name']:p for p in json.load(sys.stdin)['managed']}; p=m.get('stale-test'); print('crashed' if p and not p['alive'] else 'missing-or-alive')"
```
PASS if: prints `crashed`.

---

## Section 16 — Out-of-project behaviour

**T64** — Project commands fail outside .vigil/ directory
```bash
cd /tmp
vigil status --json; echo "status-exit:$?"
vigil start x "y" --json; echo "start-exit:$?"
vigil logs x --json; echo "logs-exit:$?"
cd /tmp/vigil-qa
```
PASS if: all three exit codes are 1 and all outputs contain `"error"`.

**T65** — scan and next work without a project
```bash
cd /tmp
vigil scan --json; echo "scan-exit:$?"
vigil next --json; echo "next-exit:$?"
cd /tmp/vigil-qa
```
PASS if: both exit codes are 0 and outputs are valid JSON (scan returns `listeners`, next returns `port`).

---

## Cleanup

```bash
vigil stop --all --json
```

---

## Return format

Return a markdown table with columns: **ID**, **Description**, **Result** (PASS / FAIL / NOTE), **Actual output or note**.

Flag any FAIL with a short description of what went wrong.
