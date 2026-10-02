# skills

Agent skills by Olav Gjerde, for GitHub Copilot CLI, Claude Code, and other
agents that read [Agent Skills](https://agentskills.io/specification).

| Skill | What it does |
|---|---|
| [`ais`](skills/ais/) | Learn AIS (Automatic Identification System): questions answered from gpsd's *AIVDM/AIVDO protocol decoding* reference. Explicit `/ais` only. |

## Install

Each skill is installed on its own. Pick one method per skill: installing the
same skill more than one way gives duplicate entries.

With the [`skills`](https://github.com/vercel-labs/skills) CLI (needs Node):

```sh
npx skills add olavgjerde/skills --list          # see what is available
npx skills add olavgjerde/skills -s ais -g       # install one skill globally
```

As a plugin, from the marketplace in this repo (one plugin per skill):

```sh
# GitHub Copilot CLI
copilot plugin marketplace add olavgjerde/skills
copilot plugin install ais@olavgjerde

# Claude Code (inside a session); plugin skills are namespaced, so /ais becomes /ais:ais
/plugin marketplace add olavgjerde/skills
/plugin install ais@olavgjerde
```

Without Node, by symlinking a clone:

```sh
git clone https://github.com/olavgjerde/skills.git ~/code/skills
for d in ~/.agents/skills ~/.claude/skills; do
  mkdir -p "$d"
  if [ -e "$d/ais" ] && [ ! -L "$d/ais" ]; then
    echo "$d/ais already exists and is not a symlink; move it aside and re-run"
  else
    ln -sfn ~/code/skills/skills/ais "$d/ais"
  fi
done
```

Link the skill directory (`skills/<name>`), not the repo root. `ln -sfn`
replaces an existing symlink; the loop skips a real directory or file instead
of touching it. Check with `copilot skill list` (look under Personal skills).

## Layout

- `skills/<name>/`: one directory per skill, holding `SKILL.md`, a
  `README.md` for humans, and anything the skill reads at run time. This is all
  that `npx skills` and the plugin install copy.
- `scripts/<name>/`: maintainer tooling for a skill, never installed.
- `.github/workflows/`: `ci.yml` checks every `skills/*/LICENSE` matches the
  root `LICENSE`; `refresh-<name>.yml` keeps generated content current.
- `.claude-plugin/marketplace.json`: the `olavgjerde` marketplace, one entry
  per skill with `source: "./skills/<name>"`, read by Copilot CLI and Claude
  Code. There is no root `plugin.json`: the repo is a marketplace, not a
  plugin.

Adding a skill: create `skills/<name>/SKILL.md`, copy the root `LICENSE`
into it, add a marketplace entry and a row to the table above.

## Licence

MIT ([LICENSE](LICENSE)), copied into each skill directory because
`npx skills` installs only that directory. A skill that bundles third-party
material carries its licence next to it; see the skill's README.
