# UI Acceptance Report

- Generated: 2026-03-31T02:33:34.107263
- Spec: `acceptance/ui_end_to_end.md`
- Browser: `auto`
- Base port: `5061`

## AC-UI-1 - FAIL

Home page loads the active debate without identity leakage

Failure:
```text
Server exited early with code 1

Traceback (most recent call last):
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/ui_acceptance.py", line 466, in run_single_criterion
    wait_for_health(base_url, timeout_seconds, process)
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/dev_workflow.py", line 130, in wait_for_health
    raise RuntimeError(f"Server exited early with code {process.returncode}")
RuntimeError: Server exited early with code 1
```

## AC-UI-2 - FAIL

Posting flow is visibly gated, then allows a structured post with a session

Failure:
```text
Server exited early with code 1

Traceback (most recent call last):
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/ui_acceptance.py", line 466, in run_single_criterion
    wait_for_health(base_url, timeout_seconds, process)
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/dev_workflow.py", line 130, in wait_for_health
    raise RuntimeError(f"Server exited early with code {process.returncode}")
RuntimeError: Server exited early with code 1
```

## AC-UI-3 - FAIL

Generating a snapshot updates the UI and verdict page

Failure:
```text
Server exited early with code 1

Traceback (most recent call last):
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/ui_acceptance.py", line 466, in run_single_criterion
    wait_for_health(base_url, timeout_seconds, process)
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/dev_workflow.py", line 130, in wait_for_health
    raise RuntimeError(f"Server exited early with code {process.returncode}")
RuntimeError: Server exited early with code 1
```

## AC-UI-4 - FAIL

Topics page renders topic rows after snapshot generation

Failure:
```text
Server exited early with code 1

Traceback (most recent call last):
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/ui_acceptance.py", line 466, in run_single_criterion
    wait_for_health(base_url, timeout_seconds, process)
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/dev_workflow.py", line 130, in wait_for_health
    raise RuntimeError(f"Server exited early with code {process.returncode}")
RuntimeError: Server exited early with code 1
```

## AC-UI-5 - FAIL

Visible modulation blocks obvious spam through the UI

Failure:
```text
Server exited early with code 1

Traceback (most recent call last):
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/ui_acceptance.py", line 466, in run_single_criterion
    wait_for_health(base_url, timeout_seconds, process)
  File "/Users/jonathanleung/Documents/C++/debate_system/scripts/dev_workflow.py", line 130, in wait_for_health
    raise RuntimeError(f"Server exited early with code {process.returncode}")
RuntimeError: Server exited early with code 1
```
