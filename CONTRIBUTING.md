# Contributing

## Layout

- `skills/<name>/`: one directory per skill, holding `SKILL.md`, a
  `README.md` for humans, and anything the skill reads at run time.
  `npx skills` and the plugin install copy this directory and nothing else.
- `scripts/<name>/`: maintainer tooling for a skill. Installs leave it out.
- `.github/workflows/`: `ci.yml` checks that each `skills/*/LICENSE` matches
  the root `LICENSE`. `refresh-<name>.yml` rebuilds a skill's generated files
  and opens a pull request when the upstream source changes.
- `.claude-plugin/marketplace.json`: the `olavgjerde` marketplace that Copilot
  CLI and Claude Code read, with one entry per skill and
  `source: "./skills/<name>"`. Each skill is its own plugin, so the repo has
  no root `plugin.json`.

## Adding a skill

Create `skills/<name>/SKILL.md` and copy the root `LICENSE` into the same
directory, since `npx skills` installs that directory alone. Then add a
marketplace entry and a line under **Skills** in the README.

## ais

`SKILL.md` uses two client fields outside the Agent Skills spec:
`disable-model-invocation`, which limits the skill to `/ais`, and
`argument-hint`. Copilot CLI and Claude Code honour them; `skills-ref validate`
reports them as unexpected fields.

### Refreshing the references

`scripts/ais/refresh.py` rebuilds `skills/ais/references/` from
https://gpsd.io/AIVDM.html. It needs `python3` and `pandoc`:

```sh
python3 scripts/ais/refresh.py                  # dry run: version, hash, added/removed/changed files
python3 scripts/ais/refresh.py --apply <sha256> # replace references/ with the build the dry run showed
```

`--apply` takes the dry run's `HTML sha256` and aborts if the page changed in
between. Never edit `references/` by hand: the next refresh overwrites it.

`.github/workflows/refresh-ais.yml` runs the same two steps every Monday, or
when you trigger it, with the pandoc version that `SOURCE.json` records. It
opens a pull request on the `refresh/ais-references` branch. For that, enable
*Allow GitHub Actions to create and approve pull requests* under Settings →
Actions → General.

To move to a newer pandoc, run `--apply` on your machine with it. The workflow
reads the new version from `SOURCE.json`.
