# ais

An AIS tutor. Ask about AIS (Automatic Identification System) and
`!AIVDM`/`!AIVDO` sentences, and it answers from the gpsd *AIVDM/AIVDO
protocol decoding* page with a link to the section it used. Run it with
`/ais <question>`; your agent won't invoke it on its own.

```text
/ais what is the difference between VDM and VDO?
/ais which message types carry a vessel's name?
/ais !AIVDM,1,1,,B,177KQJ5000G?tO`K>RA1wUbN0TKH,0*5C
```

Paste a raw sentence and it walks you through the sentence fields: talker,
fragments, channel, fill bits, and checksum. For the payload values it points
you to a decoder such as gpsd's `gpsdecode` or
[`pyais`](https://github.com/M0r13n/pyais), then explains the decoder's output
field by field.

Install it from the [repo README](../../README.md#install). It reads its
bundled `references/` and runs no commands, so it needs nothing beyond the
agent.

## Updates

`references/` holds a snapshot of the gpsd page (version in
`references/SOURCE.json`). A GitHub workflow compares it with gpsd.io every
week and opens a pull request when the page changes. Update the skill to get
the new snapshot.

## Files

- `SKILL.md`: instructions the agent follows
- `references/`: the gpsd page split into one file per section and message type, plus `index.md`
- `references/SOURCE.json`: snapshot metadata (doc version, fetch time, HTML hash, converter)
- `LICENSE` (MIT), `LICENSE-gpsd` (BSD-2-Clause, covers `references/`)

## Source and licence

Eric S. Raymond wrote [AIVDM/AIVDO protocol decoding](https://gpsd.io/AIVDM.html)
for the gpsd project. `references/` copies it under gpsd's BSD-2-Clause licence
([LICENSE-gpsd](LICENSE-gpsd)). The rest of the skill is MIT
([LICENSE](LICENSE)).
