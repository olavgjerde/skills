# Contributing

## Layout

- `skills/<name>/`: one directory per skill, holding `SKILL.md`, a
  `README.md` for humans, and anything the skill reads at run time.
  `npx skills` and the plugin install copy this directory and nothing else.
- `scripts/<name>/`: maintainer tooling for a skill. Installs leave it out.
- `scripts/plugin_version.py`: raises a plugin's version in
  `marketplace.json` (`bump NAME`) and checks that every changed skill did
  (`check BASE`).
- `.github/workflows/`: `ci.yml` checks that each `skills/*/LICENSE` matches
  the root `LICENSE`, runs the scripts' specs, and fails if a skill directory
  changed without a higher version. `refresh-<name>.yml`
  rebuilds a skill's generated files, bumps its version, and opens a pull
  request when the upstream source changes.
- `.claude-plugin/marketplace.json`: the `olavgjerde` marketplace that Copilot
  CLI and Claude Code read, with one entry per skill and
  `source: "./skills/<name>"`. Each skill is its own plugin, so the repo has
  no root `plugin.json`.

## Adding a skill

Create `skills/<name>/SKILL.md` and copy the root `LICENSE` into the same
directory, since `npx skills` installs that directory alone. Then add a
marketplace entry with `"version": "1.0.0"` and a line under **Skills** in the
README.

## Versions

Claude Code keeps users on the installed copy of a plugin until its `version`
in `marketplace.json` changes, however many commits land. So any change under
`skills/<name>/` needs a higher version in the same push or pull request:

```sh
python3 scripts/plugin_version.py bump <name>     # patch bump, prints the new version
python3 scripts/plugin_version.py check origin/main  # what CI runs: exit 1 if a changed skill kept its version
python3 -m unittest scripts/test_plugin_version.py
```

`bump` raises the patch number; raise minor or major by hand for bigger
changes. Changes outside `skills/` (READMEs at the root, `scripts/`,
workflows) need no bump. CI skips the check when it has no base commit to
compare with, such as after a force push.

## ais

`SKILL.md` uses two client fields outside the Agent Skills spec:
`disable-model-invocation`, which limits the skill to `/ais`, and
`argument-hint`. Copilot CLI and Claude Code honour them; `skills-ref validate`
reports them as unexpected fields.

### Refreshing the references

`scripts/ais/refresh.py` rebuilds `skills/ais/references/` from
https://gpsd.io/AIVDM.html. It needs `python3` and `pandoc`:

```sh
python3 scripts/ais/refresh.py           # rebuild references/ and list added/removed/changed files
python3 scripts/ais/refresh.py --check   # same report, writes nothing; exits 1 if references/ is out of date
python3 -m unittest discover -s scripts/ais  # specs for the split, index and fidelity check; no pandoc needed
```

The output depends only on the page bytes, the pandoc version and the
script; `SOURCE.json` holds no timestamps. So an unchanged page rewrites
nothing, and `git diff` shows exactly what changed upstream. Review a refresh
with `git diff`; undo it with `git checkout skills/ais/references` (and
`git clean -f skills/ais/references` for added files). Never edit
`references/` by hand: the next refresh overwrites it. The fidelity check
compares heading and table counts with the HTML and requires message types
1–27; if it fails, nothing is written.

`.github/workflows/refresh-ais.yml` runs the script every Monday, or when you
trigger it, with the pandoc version that `SOURCE.json` records. If
`references/` changed, it bumps the `ais` patch version and opens a pull
request on the `refresh/ais-references` branch with the script's report as the
body. For that, enable
*Allow GitHub Actions to create and approve pull requests* under Settings →
Actions → General.

To move to a newer pandoc, run the script on your machine with it and commit
the result. The workflow reads the new version from `SOURCE.json`.
