# ais

An AIS tutor: ask questions about AIS (Automatic Identification System) and
`!AIVDM`/`!AIVDO` sentences, answered from the gpsd *AIVDM/AIVDO protocol
decoding* page. Invoke with `/ais <question>`; it never triggers on its own.

It teaches; it does not decode. Paste a raw `!AIVDM` sentence and it explains
the sentence fields, but leaves payload decoding to a decoder such as gpsd's
`gpsdecode` or [`pyais`](https://github.com/M0r13n/pyais).

Install instructions are in the [repo README](../../README.md#install).

## Requirements

None beyond the agent: the skill only reads its bundled `references/` and runs
no commands.

## Keeping up to date

The references are a snapshot of the gpsd page (version in
`references/SOURCE.json`). A scheduled workflow checks the page weekly and
opens a pull request when it changes. Pick up a new snapshot with
`npx skills update` or `copilot plugin update ais`.

## Maintaining the references

`scripts/ais/refresh.py` (at the repo root, not part of the installed skill)
rebuilds `skills/ais/references/`. It needs `python3` and `pandoc`:

```sh
python3 scripts/ais/refresh.py                  # dry run: version, hash, added/removed/changed files
python3 scripts/ais/refresh.py --apply <sha256> # replace references/ with the build the dry run showed
```

`--apply` takes the dry run's `HTML sha256` and aborts if the page changed in
between. Never edit `references/` by hand.

`.github/workflows/refresh-ais.yml` runs the same two steps every Monday (or
on demand) with the pandoc version recorded in `SOURCE.json`, and opens a PR
on the `refresh/ais-references` branch. It needs *Allow GitHub Actions to
create and approve pull requests* enabled under Settings → Actions → General.
To move to a newer pandoc, run `--apply` locally with it; the workflow follows
`SOURCE.json`.

## Files

- `SKILL.md`: instructions the agent follows
- `references/`: the gpsd page split into one file per section and message type, plus `index.md`. Generated; do not edit.
- `references/SOURCE.json`: snapshot metadata (doc version, fetch time or local HTML file name, HTML hash, converter)
- `LICENSE` (MIT), `LICENSE-gpsd` (BSD-2-Clause, covers `references/`)

`SKILL.md` keeps two client fields outside the Agent Skills spec:
`disable-model-invocation` (explicit `/ais` use only) and `argument-hint`.
Copilot CLI and Claude Code honour them; `skills-ref validate` reports them
as unexpected fields.

## Source and licence

`references/` comes from [AIVDM/AIVDO protocol decoding](https://gpsd.io/AIVDM.html)
by Eric S. Raymond, part of the gpsd project, and falls under gpsd's
BSD-2-Clause licence ([LICENSE-gpsd](LICENSE-gpsd)). The rest of the skill is
MIT ([LICENSE](LICENSE)).
