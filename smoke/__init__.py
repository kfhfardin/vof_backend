"""Independent third-party + infrastructure verification probes.

Each probe is runnable solo (`python -m smoke.agentphone --mode smoke`) or
aggregated (`python -m smoke run --all --mode smoke`).

Three modes:
  check   - auth + connectivity only (<2s, cheap)
  smoke   - every feature we actually use (<30s, costs cents)
  repair  - smoke + verbose diagnostic output for failures

Four exit codes:
  0 - pass
  1 - functional failure (our config/contract broken)
  2 - config error (env vars missing or malformed)
  3 - upstream unavailable (third-party 5xx - not our problem)

See LLD section B and section B12 for full details.
"""
