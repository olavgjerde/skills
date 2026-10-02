# skills

Agent skills by Olav Gjerde, for Claude Code, GitHub Copilot CLI, and any
other agent that reads [Agent Skills](https://agentskills.io/specification).

## Install

Pick one way per skill: install a skill twice and your agent lists it twice.

<details>
<summary><strong>Claude Code</strong></summary>

```sh
claude plugin marketplace add olavgjerde/skills
claude plugin install ais@olavgjerde
```

Claude Code namespaces plugin skills, so you run `/ais` as `/ais:ais`. Update
with `claude plugin update ais@olavgjerde`.

</details>

<details>
<summary><strong>GitHub Copilot CLI</strong></summary>

```sh
copilot plugin marketplace add olavgjerde/skills
copilot plugin install ais@olavgjerde
```

Update with `copilot plugin update ais`.

</details>

<details>
<summary><strong>Other agents</strong></summary>

```sh
npx skills@latest add olavgjerde/skills
```

The installer asks which skills you want and which agents to install them
for. Update with `npx skills update`.

</details>

## Skills

- **[ais](./skills/ais/)**: Ask questions about AIS (Automatic Identification
  System) and get answers from gpsd's *AIVDM/AIVDO protocol decoding*
  reference. Run it with `/ais <question>`.

## Licence

MIT ([LICENSE](LICENSE)). A skill that bundles third-party material carries
that licence too; see the skill's README.
