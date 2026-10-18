# Security policy

## Scope and safety
read-only DNS queries only; real resolution is the default and `--demo` is an explicit offline mode. Inputs are validated, queries have a timeout (default 3 s), and the tool never writes or changes anything.

## What was and was not tested
**Tested (automated, in CI and locally):** exit codes and input validation (offline, with fake resolvers and the demo resolver); one manual run of real lookups with dnspython against the system resolver and `--resolver 1.1.1.1` in a container whose network answers every name with a wildcard address, so NXDOMAIN detection could not be confirmed there.

**Not tested:** NXDOMAIN/timeout behavior against real nameservers; custom `--resolver` against internal DNS; Windows/macOS; the standard-library fallback on networks with unusual resolvers.

## Reporting a problem
This is a small personal portfolio project, not a supported product. If you find a security issue, please open a GitHub issue **without** secrets, credentials or real system details, or use GitHub's "Report a vulnerability" button on the Security tab if it is enabled.
