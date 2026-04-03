1. Project Initialization

  1a. No project error
  cd /tmp && uv run vigil status
  Expected: error message mentioning vigil init, exit 1.

steff@Steffen:/tmp$ cd /tmp && uv run vigil status
No .vigil/ directory found. Run 'vigil init' to initialize a project.

  1b. Init (JSON, non-interactive)
  cd /tmp/vigil-qa
  uv run vigil init --process "web,python3 -m http.server 8765,8765" --json
  Expected: {"status": "created", ...}, .vigil/ directory exists, Vigilfile
  written.

steff@Steffen:/tmp/vigil-qa$ uv run vigil init --process "web,python3 -m http.server 8765,8765" --json
{
  "status": "created",
  "processes": [
    {
      "name": "web",
      "command": "python3 -m http.server 8765",
      "port": 8765
    }
  ]
}
steff@Steffen:/tmp/vigil-qa$ ls
Vigilfile
steff@Steffen:/tmp/vigil-qa$ cat Vigilfile
[[process]]
name = "web"
command = "python3 -m http.server 8765"
port = 8765

  1c. Init already exists
  uv run vigil init --process "web,python3 -m http.server 8765,8765" --json
  Expected: JSON error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil init --process "web,python3 -m http.server 8765,8765" --json
{
  "error": "Vigilfile already exists. Use --force to overwrite.",
  "code": 1
}

  1d. Init --force overwrites
  uv run vigil init --process "web,python3 -m http.server 8765,8765" --force
  --json
  Expected: succeeds again.

steff@Steffen:/tmp/vigil-qa$ uv run vigil init --process "web,python3 -m http.server 8765,8765" --force
  --json
Initialized vigil project with 1 process(es).
--json: command not found

  1e. Init rejects empty command (flag mode)
  uv run vigil init --process "web," --json
  Expected: error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil init --process "web," --json
{"error": "Invalid process spec 'web,': expected format is name,command[,port].", "code": 1}

  ---
  2. vigil start / vigil status

  2a. Start a process
  uv run vigil start web "python3 -m http.server 8765" --json
  Expected: {"name": "web", "pid": <N>, "status": "started"}.

steff@Steffen:/tmp/vigil-qa$   uv run vigil start web "python3 -m http.server 8765" --json
{"name": "web", "pid": 105262, "status": "started"}

  2b. Status shows it alive
  uv run vigil status --json
  Expected: managed[0].alive == true, managed[0].ports contains 8765 (may take
   a moment to bind).

steff@Steffen:/tmp/vigil-qa$ uv run vigil status --json
{
  "managed": [
    {
      "name": "web",
      "command": "python3 -m http.server 8765",
      "pid": 105262,
      "alive": true,
      "ports": [
        8765
      ],
      "docker": null
    }
  ]
}

  2c. Human-readable status
  uv run vigil status
  Expected: ● alive with PID and :8765.

steff@Steffen:/tmp/vigil-qa$ uv run vigil status
  web          ● alive    PID 105262  :8765  (python3 -m http.server 8765)

  2d. Start duplicate (no --force)
  uv run vigil start web "python3 -m http.server 8765" --json
  Expected: JSON error about already running, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start web "python3 -m http.server 8765" --json
{"error": "Process 'web' crashed (pid 105262). Use --force to start a fresh one.", "code": 1}

Doesnt give error, just crashes the running process.

  2e. Start with --force replaces
  uv run vigil start web "python3 -m http.server 8765" --force --json
  Expected: success, new PID.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start web "python3 -m http.server 8765" --force --json
{"name": "web", "pid": 105557, "status": "started"}

  2f. Start rejects empty name
  uv run vigil start "" "python3 -m http.server 8765" --json
  Expected: error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start "" "python3 -m http.server 8765" --json
{"error": "Process name cannot be empty.", "code": 1}

  2g. Start with --env
  uv run vigil start env-test "env" --env MYVAR=hello --json
  Expected: starts. Then vigil logs env-test should show MYVAR=hello in
  output.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start env-test "env" --env MYVAR=hello --json
{"name": "env-test", "pid": 105863, "status": "started"}

  2h. Start with --cwd
  mkdir -p /tmp/vigil-qa/subdir
  uv run vigil start cwd-test "pwd" --cwd /tmp/vigil-qa/subdir --json
  sleep 1
  uv run vigil logs cwd-test
  Expected: log shows /tmp/vigil-qa/subdir.

steff@Steffen:/tmp/vigil-qa$ mkdir -p /tmp/vigil-qa/subdir
steff@Steffen:/tmp/vigil-qa$ uv run vigil start cwd-test "pwd" --cwd /tmp/vigil-qa/subdir --json
{"name": "cwd-test", "pid": 105983, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil logs cwd-test
/tmp/vigil-qa/subdir

  ---
  3. vigil wait

  3a. Wait for running process
  uv run vigil wait web --timeout 10 --json
  Expected: {"name": "web", "status": "ready"}, exit 0.

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait web --timeout 10 --json
{"name": "web", "status": "died", "error": "Process 'web' died while waiting for readiness."}
steff@Steffen:/tmp/vigil-qa$ uv run vigil start web "python3 -m http.server 8765" --force --json
{"name": "web", "pid": 106206, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil wait web --timeout 10 --json
{"name": "web", "status": "died", "error": "Process 'web' died while waiting for readiness."}


  3b. Wait with --port
  uv run vigil wait web --port 8765 --timeout 5 --json
  Expected: ready.

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait web --port 8765 --timeout 5 --json
{"name": "web", "status": "died", "error": "Process 'web' died while waiting for readiness."}

  3c. Wait with --http
  uv run vigil wait web --http --timeout 10 --json
  Expected: ready (python http.server responds to GET /).

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait web --http --timeout 10 --json
{"name": "web", "status": "died", "error": "Process 'web' died while waiting for readiness."}

  3d. Wait with --http=/path
  uv run vigil wait web --http=/nonexistent --timeout 5 --json
  Expected: ready (any HTTP response counts, including 404).

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait web --http=/nonexistent --timeout 5 --json
{"name": "web", "status": "died", "error": "Process 'web' died while waiting for readiness."}

  3e. Wait timeout
  uv run vigil start slow "sleep 60" --json
  uv run vigil wait slow --port 9999 --timeout 2 --json
  Expected: {"status": "timeout", ...}, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start slow "sleep 60" --json
{"name": "slow", "pid": 106484, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil wait slow --port 9999 --timeout 2 --json
{"name": "slow", "status": "timeout", "error": "Process 'slow' did not become ready within 2s."}

  3f. Wait on died process (exit 2)
  uv run vigil start dying "sleep 0.1" --json
  sleep 1
  uv run vigil wait dying --timeout 5 --json
  echo "Exit: $?"
  Expected: {"status": "died", ...}, exit 2.

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait dying --timeout 5 --json
{"name": "dying", "status": "died", "error": "Process 'dying' died while waiting for readiness."}
steff@Steffen:/tmp/vigil-qa$ echo "Exit: $?"
Exit: 2

  3g. Wait unknown name
  uv run vigil wait nobody --json
  Expected: JSON error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil wait nobody --json
{"error": "No managed process named 'nobody'", "code": 1}

  ---
  4. vigil logs

  4a. Tail logs
  uv run vigil logs web --tail 20
  Expected: last 20 lines of python http.server output.

steff@Steffen:/tmp/vigil-qa$ uv run vigil logs web --tail 20
    self.socket.bind(self.server_address)
OSError: [Errno 98] Address already in use
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/usr/lib/python3.12/http/server.py", line 1314, in <module>
    test(
  File "/usr/lib/python3.12/http/server.py", line 1261, in test
    with ServerClass(addr, HandlerClass) as httpd:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/socketserver.py", line 457, in __init__
    self.server_bind()
  File "/usr/lib/python3.12/http/server.py", line 1308, in server_bind
    return super().server_bind()
           ^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/http/server.py", line 136, in server_bind
    socketserver.TCPServer.server_bind(self)
  File "/usr/lib/python3.12/socketserver.py", line 473, in server_bind
    self.socket.bind(self.server_address)
OSError: [Errno 98] Address already in use

  4b. JSON logs
  uv run vigil logs web --tail 5 --json
  Expected: {"lines": [...]}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil logs web --tail 5 --json
{"lines": ["  File \"/usr/lib/python3.12/http/server.py\", line 136, in server_bind", "    socketserver.TCPServer.server_bind(self)", "  File \"/usr/lib/python3.12/socketserver.py\", line 473, in server_bind", "    self.socket.bind(self.server_address)", "OSError: [Errno 98] Address already in use"]}

  4c. Unknown process
  uv run vigil logs nobody --json
  Expected: JSON error, exit 1.

uv run vigil logs nobody --json

  4d. Log file exists at correct path
  ls /tmp/vigil-qa/.vigil/logs/web.log
  Expected: file exists.

steff@Steffen:/tmp/vigil-qa$ ls /tmp/vigil-qa/.vigil/logs/web.log
/tmp/vigil-qa/.vigil/logs/web.log

  ---
  5. vigil stop

  5a. Stop a process
  uv run vigil stop web --json
  Expected: {"name": "web", "status": "stopped"}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil stop web --json
{"name": "web", "status": "stopped"}

  5b. Status after stop — not shown
  uv run vigil status --json
  Expected: web is absent from managed.

steff@Steffen:/tmp/vigil-qa$ uv run vigil status --json
{
  "managed": [
    {
      "name": "env-test",
      "command": "env",
      "pid": null,
      "alive": false,
      "crashed": true,
      "ports": [],
      "docker": null
    },
    {
      "name": "cwd-test",
      "command": "pwd",
      "pid": null,
      "alive": false,
      "crashed": true,
      "ports": [],
      "docker": null
    },
    {
      "name": "slow",
      "command": "sleep 60",
      "pid": null,
      "alive": false,
      "crashed": true,
      "ports": [],
      "docker": null
    },
    {
      "name": "dying",
      "command": "sleep 0.1",
      "pid": null,
      "alive": false,
      "crashed": true,
      "ports": [],
      "docker": null
    }
  ]
}

  5c. Log trimmed after stop
  wc -l /tmp/vigil-qa/.vigil/logs/web.log
  Expected: ≤ 500 lines.

steff@Steffen:/tmp/vigil-qa$ wc -l /tmp/vigil-qa/.vigil/logs/web.log
36 /tmp/vigil-qa/.vigil/logs/web.log

  5d. Stop unknown
  uv run vigil stop nobody --json
  Expected: JSON error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil stop nobody --json
{"error": "No managed process named 'nobody'.", "code": 1}

  5e. Stop already-crashed process

  First, start something and kill it externally:
  uv run vigil start crashme "sleep 60" --json
  # Note the PID from output, e.g. 12345
  kill <pid>
  sleep 1
  uv run vigil stop crashme --json
  Expected: succeeds (idempotent — cleans up statefile even though already
  dead).

steff@Steffen:/tmp/vigil-qa$ uv run vigil start crashme "sleep 60" --json
{"name": "crashme", "pid": 109201, "status": "started"}
steff@Steffen:/mnt/c/Users/Steff$ kill 109201
steff@Steffen:/tmp/vigil-qa$ uv run vigil stop crashme --json
{"name": "crashme", "status": "stopped"}

Ideally more context given here. "The process was dead. Cleaned up Vigilfile

  5f. Stop --all
  uv run vigil start a "sleep 60" --json
  uv run vigil start b "sleep 60" --json
  uv run vigil stop --all --json
  Expected: both stopped. vigil status shows empty.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start b "sleep 60" --json
{"name": "b", "pid": 109852, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil start a "sleep 60" --json
{"name": "a", "pid": 109876, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil stop --all --json
{"status": "stopped", "names": ["env-test", "cwd-test", "slow", "dying", "b", "a"]}

  ---
  6. vigil restart

  6a. Restart a process
  uv run vigil start web "python3 -m http.server 8765" --json
  OLD_PID=$(uv run vigil status --json | python3 -c "import sys,json;
  print(json.load(sys.stdin)['managed'][0]['pid'])")
  uv run vigil restart web --json
  Expected: {"status": "restarted"} with a new PID.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start web "python3 -m http.server 8765" --json
{"name": "web", "pid": 109964, "status": "started"}

steff@Steffen:/tmp/vigil-qa$ OLD_PID=$(uv run vigil status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['managed'][0][
'pid'])")
steff@Steffen:/tmp/vigil-qa$ uv run vigil restart web --json
{"name": "web", "pid": 110110, "status": "restarted"}

  6b. Restart unknown
  uv run vigil restart nobody --json
  Expected: JSON error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil restart nobody --json
{"error": "No managed process named 'nobody'.", "code": 1}

  ---
  7. vigil remove

  7a. Remove crashed entry
  uv run vigil start toremove "sleep 60" --json
  RPID=$(uv run vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='toremove']")
  kill $RPID
  sleep 1
  uv run vigil remove toremove --json
  Expected: {"name": "toremove", "status": "removed"}. Absent from status.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start toremove "sleep 60" --json
{"name": "toremove", "pid": 110420, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ RPID=$(uv run vigil status --json | python3 -c "import sys,json; [print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='toremove']")
steff@Steffen:/tmp/vigil-qa$ kill $RPID
steff@Steffen:/tmp/vigil-qa$ uv run vigil remove toremove --json
{"name": "toremove", "status": "removed"}

  7b. Remove alive process (no --force)
  uv run vigil start alive "sleep 60" --json
  uv run vigil remove alive --json
  Expected: error (process is alive), exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start alive "sleep 60" --json
{"name": "alive", "pid": 110608, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil remove alive --json
{"error": "Process 'alive' is still running (pid 110608). Use --force to remove the registry entry without stopping it.", "code": 1}

  7c. Remove alive with --force
  uv run vigil remove alive --force --json
  Expected: success. Process is still running (check ps) but absent from
  statefile.

steff@Steffen:/tmp/vigil-qa$ uv run vigil remove alive --force --json
{"name": "alive", "status": "removed"}

  ---
  8. vigil scan

  8a. Default scan
  uv run vigil start scantest "python3 -m http.server 8766" --json
  sleep 1
  uv run vigil scan --json
  Expected: listeners contains entry with port 8766.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start scantest "python3 -m http.server 8766" --json
{"name": "scantest", "pid": 111480, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil scan --json
{
  "listeners": [
    {
      "port": 8765,
      "pid": 105262,
      "process": "python3",
      "docker": null
    },
    {
      "port": 8766,
      "pid": 111480,
      "process": "python3",
      "docker": null
    },
    {
      "port": 5282,
      "pid": 1960,
      "process": "node",
      "docker": null
    }
  ]
}

  8b. Specific port
  uv run vigil scan --port 8766 --json
  Expected: exactly one listener on 8766.

uv run vigil scan --port 8766 --json
{
  "listeners": [
    {
      "port": 8766,
      "pid": 111480,
      "process": "python3",
      "docker": null
    }
  ]
}

  8c. Range filter
  uv run vigil scan --range 8760-8770 --json
  Expected: shows 8766.

steff@Steffen:/tmp/vigil-qa$ uv run vigil scan --range 8760-8770 --json
{
  "listeners": [
    {
      "port": 8766,
      "pid": 111480,
      "process": "python3",
      "docker": null
    },
    {
      "port": 8765,
      "pid": 105262,
      "process": "python3",
      "docker": null
    }
  ]
}

  8d. Empty port
  uv run vigil scan --port 19999 --json
  Expected: {"listeners": []}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil scan --port 19999 --json
{
  "listeners": []
}

  8e. --all flag
  uv run vigil scan --all --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['listeners']), 'listeners')"
  Expected: more listeners than the dev-range scan (includes system ports).

steff@Steffen:/tmp/vigil-qa$ uv run vigil scan --all --json | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['listeners']), 'listeners')"
9 listeners

  ---
  9. vigil next

  9a. Default start
  uv run vigil next --json
  Expected: {"port": N} where N ≥ 3000 and nothing is listening on it.

steff@Steffen:/tmp/vigil-qa$ uv run vigil next --json
{"port": 3000}

  9b. Specific start
  uv run vigil next 8766 --json
  Expected: {"port": N} where N > 8766 (8766 is occupied).

steff@Steffen:/tmp/vigil-qa$   uv run vigil next 8766 --json
{"port": 8767}

  9c. Count > 1
  uv run vigil next 9000 --count 3 --json
  Expected: {"ports": [A, B, C]}, three consecutive free ports.

steff@Steffen:/tmp/vigil-qa$   uv run vigil next 9000 --count 3 --json
{"ports": [9000, 9001, 9002]}

  9d. Invalid start
  uv run vigil next 65536 --json
  Expected: error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil next 65536 --json
{"error": "start port 65536 is above the maximum valid port 65535", "code": 1}

  ---
  10. vigil health

  10a. Healthy process
  uv run vigil health --json
  Expected: entry for scantest with healthy: true, HTTP status code present.

steff@Steffen:/tmp/vigil-qa$  uv run vigil health --json
{
  "processes": []
}

  10b. Custom endpoint
  uv run vigil health --endpoint /nonexistent --json
  Expected: still healthy: true (404 counts as healthy per spec).

steff@Steffen:/tmp/vigil-qa$ uv run vigil health --endpoint /nonexistent --json
{
  "processes": []
}

  10c. Unhealthy (stopped but state file check)

  Start a process with a port, then kill it externally without vigil stop:
  uv run vigil start unhealthyme "python3 -m http.server 8767" --json
  sleep 1
  PID=$(uv run vigil status --json | python3 -c "import sys,json;[print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='unhealthyme']")
  kill $PID
  sleep 1
  uv run vigil health --json
  Expected: unhealthyme absent (it's crashed, health only checks alive
  processes).

steff@Steffen:/tmp/vigil-qa$ uv run vigil start unhealthyme "python3 -m http.server 8767" --json
{"name": "unhealthyme", "pid": 112236, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ PID=$(uv run vigil status --json | python3 -c "import sys,json;[print(p['pid']) for p in json.load(sys.stdin)['managed'] if p['name']=='unhealthyme']")
steff@Steffen:/tmp/vigil-qa$ kill $PID
steff@Steffen:/tmp/vigil-qa$ uv run vigil health --json
{
  "processes": []
}

  ---
  11. vigil free

  11a. Free an unmanaged port
  python3 -m http.server 8768 &
  BGPID=$!
  sleep 0.5
  uv run vigil free 8768 --json
  Expected: {"port": 8768, "freed": true, "was": "unmanaged"}.

steff@Steffen:/tmp/vigil-qa$ python3 -m http.server 8768 &
[1] 112386
steff@Steffen:/tmp/vigil-qa$ Serving HTTP on 0.0.0.0 port 8768 (http://0.0.0.0:8768/) ...
steff@Steffen:/tmp/vigil-qa$ BGPID=$!
steff@Steffen:/tmp/vigil-qa$ uv run vigil free 8768 --json
{"port": 8768, "freed": true, "was": "unmanaged"}

  11b. Free a managed port
  uv run vigil start freetest "python3 -m http.server 8769" --json
  sleep 1
  uv run vigil free 8769 --json
  Expected: {"was": "managed"}. Process absent from vigil status.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start freetest "python3 -m http.server 8769" --json
{"name": "freetest", "pid": 112941, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil free 8769 --json
{"port": 8769, "freed": true, "was": "managed"}

steff@Steffen:/tmp/vigil-qa$ vigil status
  web          ✖ crashed  (python3 -m http.server 8765)
  scantest     ✖ crashed  (python3 -m http.server 8766)
  unhealthyme  ✖ crashed  (python3 -m http.server 8767)

  11c. Free an already-free port
  uv run vigil free 19999 --json
  Expected: {"freed": true, "was": "free"}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil free 19999 --json
{"port": 19999, "freed": true, "was": "free"}

  ---
  12. vigil open

  12a. Open by port (--json, no browser)
  uv run vigil open 8765 --json
  Expected: {"url": "http://localhost:8765"}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil open 8765 --json
{"url": "http://localhost:8765"}

  12b. Open by name (--json)
  uv run vigil start opentest "python3 -m http.server 8770" --json
  sleep 1
  uv run vigil open opentest --json
  Expected: {"url": "http://localhost:8770"}.

steff@Steffen:/tmp/vigil-qa$ uv run vigil start opentest "python3 -m http.server 8770" --json
{"name": "opentest", "pid": 113159, "status": "started"}
steff@Steffen:/tmp/vigil-qa$ uv run vigil open opentest --json
{"url": "http://localhost:8770"}

  12c. Open unknown name
  uv run vigil open nobody --json
  Expected: JSON error, exit 1.

steff@Steffen:/tmp/vigil-qa$ uv run vigil open nobody --json
{"error": "No process named 'nobody'", "code": 1}

  12d. Open with Vigilfile url override

  Edit the Vigilfile to add url = "http://localhost:8770/custom/" to
  opentest's entry, then:
  uv run vigil open opentest --json
  Expected: {"url": "http://localhost:8770/custom/"}.

The Vigilfile did not have opentest entry:   GNU nano 7.2                                                     Vigilfile
[[process]]
name = "web"
command = "python3 -m http.server 8765"
port = 8765


steff@Steffen:/tmp/vigil-qa$ vigil status
  web          ✖ crashed  (python3 -m http.server 8765)
  scantest     ✖ crashed  (python3 -m http.server 8766)
  unhealthyme  ✖ crashed  (python3 -m http.server 8767)
  opentest     ✖ crashed  (python3 -m http.server 8770)

it crashed but it was never in the vigilfile i think


  ---
  13. vigil up / vigil down

  13a. Setup Vigilfile
  cat > /tmp/vigil-qa/Vigilfile << 'EOF'
  [[process]]
  name = "svc-a"
  command = "python3 -m http.server 8771"
  port = 8771
  order = 1

  [[process]]
  name = "svc-b"
  command = "python3 -m http.server 8772"
  port = 8772
  order = 2
  EOF

steff@Steffen:/tmp/vigil-qa$ cat > /tmp/vigil-qa/Vigilfile << 'EOF'
  [[process]]
  name = "svc-a"
  command = "python3 -m http.server 8771"
  port = 8771
  order = 1

  [[process]]
  name = "svc-b"
  command = "python3 -m http.server 8772"
  port = 8772
  order = 2
  EOF
>
> ^C
steff@Steffen:/tmp/vigil-qa$ cat Vigilfile
[[process]]
name = "web"
command = "python3 -m http.server 8765"
port = 8765
steff@Steffen:/tmp/vigil-qa$ cat > /tmp/vigil-qa/Vigilfile << 'EOF'
  [[process]]
  name = "svc-a"
  command = "python3 -m http.server 8771"
  port = 8771
  order = 1

  [[process]]
  name = "svc-b"
  command = "python3 -m http.server 8772"
  port = 8772
  order = 2
  EOF

> ^^C
steff@Steffen:/tmp/vigil-qa$ cat Vigilfile
[[process]]
name = "web"
command = "python3 -m http.server 8765"
port = 8765

  13b. vigil up
  uv run vigil up --json
  Expected: both started, status: "started" for each.

  13c. vigil up idempotent (already running)
  uv run vigil up --json
  Expected: both status: "skipped".

  13d. vigil up --force restarts
  uv run vigil up --force --json
  Expected: both started with new PIDs.

  13e. vigil up --only subset
  uv run vigil stop svc-a --json
  uv run vigil up --only svc-a --json
  Expected: only svc-a started; svc-b unchanged.

  13f. vigil down (reverse order)
  uv run vigil down --json
  Expected: results list shows svc-b stopped first, then svc-a (reverse of
  startup order).

  13g. vigil up with a failing process

  Corrupt the command so it fails:
  cat > /tmp/vigil-qa/Vigilfile << 'EOF'
  [[process]]
  name = "good"
  command = "python3 -m http.server 8773"
  port = 8773
  order = 1

  [[process]]
  name = "bad"
  command = "this-command-does-not-exist"
  order = 2
  EOF
  uv run vigil up --json
  echo "Exit: $?"
  Expected: good started, bad failed. Exit code 1 (note: spec says 2 for
  partial — this is a known gap to verify).

  ---
  14. Error JSON format

  Verify errors always come as JSON on stdout (not stderr) when --json is
  passed:

  uv run vigil stop nobody --json > /tmp/out.json 2>/tmp/err.txt
  cat /tmp/out.json   # should have {"error": "...", "code": 1}
  cat /tmp/err.txt    # should be empty

  ---
  15. State file integrity

  15a. Atomic write (no corruption on interrupt)
  cat /tmp/vigil-qa/.vigil/state.json
  python3 -c "import json; json.load(open('/tmp/vigil-qa/.vigil/state.json'))"
  Expected: valid JSON.

  15b. PID reuse protection — stale entry cleaned up

  After any process dies externally (not via vigil stop), its entry should
  remain in status as crashed: true, not silently disappear.

  uv run vigil start staletest "sleep 60" --json
  PID=$(...)
  kill $PID
  sleep 1
  uv run vigil status --json
  Expected: staletest present with alive: false, crashed: true.

  ---
  16. Out-of-project error

  From any directory without .vigil/:

  cd /tmp
  uv run vigil status --json
  uv run vigil start x "y" --json
  uv run vigil logs x --json
  Each: expected JSON error mentioning vigil init, exit 1.

  vigil scan and vigil next should still work without a project:
  uv run vigil scan --json
  uv run vigil next --json
  Expected: succeed without a project root.
