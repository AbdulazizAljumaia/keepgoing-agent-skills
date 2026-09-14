---
name: loop
description: Use after a runtime, test, installation, validation, or publication action fails so the next attempt changes a falsifiable hypothesis instead of repeating identical inputs.
---

# Loop

1. Capture the action, observation, exact evidence, and exit code.
2. Compare the evidence with the owning node's exit condition.
3. State one falsifiable root-cause hypothesis.
4. Make one deliberate change that tests that hypothesis.
5. Retest with bounded output and record the result.
6. Change strategy after two failed hypotheses, inspect adjacent dependencies after three attempts, and stop with evidence after five attempts.
