# SoccerNet fixtures

Two different SoccerNet products live here. They have **different provenance**:

## `gsr/`, REAL data, sliced

`gsr/SNGS-056/Labels-GameState.json` and `gsr/SNGS-035/Labels-GameState.json` are
genuine bytes from the **SN-GSR-2025** `valid.zip` on Hugging Face
(`SoccerNet/SN-GSR-2025`, repo commit `ce84ee7d9acb2f9fe999ceed2b38e303ffa5efb9`,
dataset `info.version == "1.3"`). They were obtained with HTTP range requests against
the (public, ungated) 11.2 GB `valid.zip` and then sliced down to 3 frames each:

| fixture   | frames kept                 | why |
|-----------|-----------------------------|-----|
| SNGS-056  | `2056000001..2056000003`    | happy path: every annotation has a non-null `bbox_pitch` |
| SNGS-035  | `2035000376..2035000378`    | straddles a calibration loss: frame `...376` has `bbox_pitch`, frames `...377`/`...378` have `"bbox_pitch": null` on **every** object |

Only `info.seq_length` was rewritten (750 -> 3) to stay consistent with the slice.
Every other byte, key name and numeric value is untouched original data.

## `mot/`, SYNTHETIC but schema-faithful

`mot/SNMOT-116/` is **hand-written**, because SoccerNet-Tracking (`task="tracking"` /
`task="tracking-2023"`) sits behind the NDA-password ownCloud server and could not be
downloaded. Every key name and column order was copied from documented, verified
sources, see `docs/schema_notes/soccernet.md` for the per-field citation table.
The numbers themselves are invented (loosely traced from the real GSR bboxes above).
Do not treat these pixel values or jersey numbers as real annotations.
