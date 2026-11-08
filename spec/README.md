# Spec

The contract shared by the server and every SDK. Change the spec first, then the code.

- [`flag-config.md`](flag-config.md): the flag configuration format SDKs download.
- [`evaluation.md`](evaluation.md): evaluation order, operators, semver, rollout hashing, reason codes.
- [`streaming.md`](streaming.md): keys, snapshot and stream protocol, browser evaluation, events.
- `test-vectors/evaluation.json` and `bucketing.json`: `{flag, user, expected}` and
  `{salt, value, bucket}` cases. **Every implementation must pass all of them**
  (`sdks/python/tests/test_conformance.py`, `sdks/typescript/tests/conformance.test.ts`).
- `test-vectors/generate.py`: writes the JSON files. Expected values in it are hand-specified,
  not computed by an engine, so the vectors test the engines rather than echo them.
  Regenerate with `python spec/test-vectors/generate.py spec/test-vectors`.
