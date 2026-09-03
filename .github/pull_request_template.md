<!-- PocketForge PR checklist convention (infra-251 D1). Keep all three sections. -->

## Summary

<!-- What does this PR change, and why? 1–3 sentences. -->

## Test plan

<!-- How you verified this change BEFORE merge — real, checkable steps, not "ran tests".
     Check a box ONLY when that step is actually done; an unchecked box means
     not-done and the review gate verifies each box against the diff.
     Do NOT add an item for this PR's own review gate (e.g. "Copilot review green"):
     the required check already enforces it, and the reviewer cannot verify its
     own outcome — it will block as ambiguous.
     Do NOT phrase an item to assert a result you cannot have observed yet at
     write time (a post-merge redeploy, a live-host restart, a follow-up soak):
     same problem — the reviewer holds it ambiguous/blocking. Record such a step
     one of two sanctioned ways instead:
       (a) leave the box unchecked with a tracking ref INLINE in that same line,
           e.g. "- [ ] Redeploy on pf-node-01 (post-merge, tracked in tsp-1234)"
           — a bead id / owner/repo#N / GitHub URL; a ref elsewhere in the body
           does NOT count, so the guard routes it to a deferred note; or
       (b) if nothing needs pre-merge verification, drop the checkbox entirely and
           write it as prose (under Summary or a "Post-merge follow-up" note) —
           prose is never investigated as a checklist item. -->

- [ ] 

## Related PRs

<!-- Full URLs (https://github.com/<owner>/<repo>/pull/<n>) or owner/repo#N for
     same-change siblings, the PR this builds on, or context PRs. Bare #N is NOT
     parsed by the review gate — write the full form. "None" if truly standalone. -->

None
