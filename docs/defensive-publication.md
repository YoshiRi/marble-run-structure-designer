# Defensive publication policy

The project is intended to be developed openly. For techniques that may be
novel enough to matter for later patent disputes, the project should preserve a
clear public technical record.

Examples include:

- combined assembly / stability / routing / inventory validation of modular
  marble-run layouts;
- recursive support-load and center-of-mass propagation across rail structures;
- layout-generation grammars constrained by buildability and stability;
- construction-assist derivation from a validated layout graph.

## Publication procedure

For a meaningful algorithmic milestone:

1. describe the method sufficiently in `docs/` so that an engineer can
   understand the approach;
2. commit the implementation and tests;
3. create a versioned Git tag / GitHub Release;
4. include the release date and relevant design document in the release notes;
5. optionally archive the release in a durable public archive such as Zenodo.

## Important limitation

A **private repository commit is not being represented here as a public
defensive publication**. The prior-art value of this record depends on when and
how the material actually becomes publicly accessible.

This policy is intended as engineering recordkeeping, not as a substitute for
professional patent advice. If the project team may want to seek patent
protection itself, publication timing should be reviewed before making the
relevant material public.
