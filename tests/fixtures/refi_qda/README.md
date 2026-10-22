# REFI-QDA schemas

`Codebook.xsd` and `Project.xsd`, version 1.0, from the REFI-QDA standard.
Mirrored from the openqda/refi-tools repository, which republishes what
qdasoftware.org distributes behind a share link.

**They are vendored on purpose.** The suite is offline and deterministic, and a
conformance test that fetches a schema over the network is a test that fails on
a train — and, worse, one that silently changes meaning when the remote file
does. Pinning the copy means a schema change shows up as a deliberate update to
this folder rather than as a mysterious red build.

They are validation fixtures only. Nothing in `core/` or `app/` reads them, so
they do not ship in either build.

## What validating against them caught

Both errors were invisible to every other test, because the reader and the
writer in this codebase agreed with each other:

- The codebook namespace was written `urn:QDA-XML:codebook:1:0` — a colon where
  the standard has a dot.
- `VariableValue` was written before `PlainTextSelection`. `TextSourceType` is
  an `xsd:sequence`, so the order is part of validity rather than presentation.

**Two agreeing implementations of a misreading look exactly like a correct
one.** That is the whole argument for keeping these files.
