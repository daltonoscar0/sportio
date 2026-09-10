# SoccerNet, tracking (SN-MOT) and Game State Reconstruction (SN-GSR)

Recon date: 2026-08-25. Everything below was verified against live sources; the
"Provenance" column of each table says which one.

**Headline result:** the GSR annotations are **NOT gated**. `SoccerNet/SN-GSR-2025` on
Hugging Face is `"gated": false, "private": false` and served anonymously. The older
`gamestate-2024` / `tracking` / `tracking-2023` tasks *are* gated, behind an
HTTP-Basic ownCloud server that needs the NDA password. See
[What is gated and what is not](#what-is-gated-and-what-is-not).

---

## 1. The `SoccerNet` pip package

Verified from `https://pypi.org/pypi/SoccerNet/json`:

| field | value |
|---|---|
| name | `SoccerNet` (import as `SoccerNet`, sdist named `soccernet`) |
| latest version | **0.1.62**, uploaded `2025-01-06T15:00:03` |
| summary | `SoccerNet SDK` |
| homepage | `https://github.com/SoccerNet/SoccerNet` |
| releases | 186 |
| install deps | `tqdm`, `scikit-video`, `matplotlib`, `google-measurement-protocol`, `pycocoevalcap`, `huggingface_hub[cli]`, `boto3` |

The download API (read out of `SoccerNet/Downloader.py` in the 0.1.62 sdist):

```python
class SoccerNetDownloader(OwnCloudDownloader):
    def __init__(self, LocalDirectory,
                 OwnCloudServer="https://exrcsdrive.kaust.edu.sa/public.php/webdav/"):
        ...
        self.password = None

    def downloadDataTask(self, task, split=["train","valid","test","challenge"],
                         verbose=True, password="SoccerNet",   # Generic password for public data
                         version=None, source="HuggingFace"):
```

Note `password="SoccerNet"` is the **default** and the inline comment in the source
literally reads `# Generic password for public data`. That string is the public
password; NDA tasks need a different one.

`downloadFile` return codes (from the source comments):

```
0: successfully downloaded   1: HTTPError            2: unsupported error
3: file already exist locally 4: password is None     5: user is None
```

Each gated task hardcodes a `user=` value that is really an ownCloud public-share
token, e.g. `user="OP7fl7h25NqGfcN"` for `tracking-2023` splits and
`user="PvYoZG1INJEp7fk"` for `tracking-2023` ground truth. Auth is
`urllib.request.HTTPBasicAuthHandler` against `exrcsdrive.kaust.edu.sa`.

### Task names relevant to us

| `task=` | transport | splits accepted | gated? |
|---|---|---|---|
| `"gamestate-2025"` | `huggingface_hub.snapshot_download(repo_id="SoccerNet/SN-GSR-2025", repo_type="dataset", revision="main", allow_patterns=["*"+s+".zip" for s in split])` | `train`,`valid`,`test`,`challenge` | **no** |
| `"gamestate-2024"` | ownCloud, `user="iOJmJH6rYnx7mOS"`; labels `user="94cEKBCjtwplXc1"` | + `test_labels`, `challenge_labels` | yes (NDA password) |
| `"tracking"` (2022) | ownCloud, `user="o9tzUs2GcuEwcnr"`; labels `user="qWNjAzjEI6hezNf"` | `train`,`test`,`challenge`,`test_labels`,`challenge_labels` | yes |
| `"tracking-2023"` | ownCloud, `user="OP7fl7h25NqGfcN"`; labels `user="PvYoZG1INJEp7fk"` | as above (files are `challenge2023.zip`, `test2023-private.zip`, `challenge2023-private.zip`) | yes |

`downloadRAWVideo(dataset="SoccerNet-Tracking")` fetches
`single_camera_games_public.zip` with `user="Jk85T1yV7DKMcCI"` and
`password=self.password` (i.e. the attribute, which defaults to `None` -> return code 4).

The **canonical snippets**, as printed in the upstream READMEs:

```python
# SoccerNet-Tracking (sn-tracking README)
from SoccerNet.Downloader import SoccerNetDownloader
mySoccerNetDownloader = SoccerNetDownloader(LocalDirectory="path/to/SoccerNet")
mySoccerNetDownloader.downloadDataTask(task="tracking", split=["train","test","challenge"])
mySoccerNetDownloader.downloadDataTask(task="tracking-2023", split=["train", "test", "challenge"])
```

```python
# SoccerNet-gamestate (sn-gamestate README)
from SoccerNet.Downloader import SoccerNetDownloader
mySoccerNetDownloader = SoccerNetDownloader(LocalDirectory="data/SoccerNetGS")
mySoccerNetDownloader.downloadDataTask(task="gamestate-2024",
                                       split=["train", "valid", "test", "challenge"])
```

`tracklab`'s own auto-downloader (`tracklab/wrappers/dataset/soccernet/soccernet_game_state.py`,
function `download_dataset`) uses `task="gamestate-2025"`, i.e. the ungated HF path.

---

## 2. What is gated and what is not

Measured, not guessed:

```
GET https://huggingface.co/api/datasets/SoccerNet/SN-GSR-2025
  -> "private": false, "gated": false, "disabled": false, downloads 830
     siblings: .gitattributes, README.md, challenge.zip, test.zip, train.zip, valid.zip
     license: gpl-3.0
HEAD https://huggingface.co/datasets/SoccerNet/SN-GSR-2025/resolve/main/valid.zip
  -> 302 -> 200, x-linked-size: 11169497921 (11.2 GB), accept-ranges: bytes
     x-repo-commit: ce84ee7d9acb2f9fe999ceed2b38e303ffa5efb9
```

No token, no NDA, no login. **Range requests are supported**, which is how the
fixtures in `tests/fixtures/soccernet/gsr/` were obtained without pulling 11.2 GB
(read the ZIP64 central directory from the tail, then range-fetch one deflate member).

| asset | gated? | how you get it |
|---|---|---|
| SN-GSR-2025 `train/valid/test/challenge.zip` (images + `Labels-GameState.json`) | **NO** | anonymous HTTPS from Hugging Face |
| SoccerNet-Tracking `tracking` / `tracking-2023` zips (`img1/`, `gt/gt.txt`, `det/det.txt`, `seqinfo.ini`, `gameinfo.ini`) | YES | NDA password -> `downloadDataTask(task="tracking-2023", ..., password="<NDA>")` |
| `gamestate-2024` zips | YES | NDA password (superseded by `gamestate-2025`, use that instead) |
| test/challenge **label** zips for tracking | YES, and separately | different ownCloud share token, same NDA password |
| `single_camera_games_public.zip` raw videos | YES | NDA password |
| `SoccerNet` pip package + all source code | NO | PyPI / GitHub |

---

## 3. SN-GSR-2025 on-disk layout (verified from the real archive)

Read out of the ZIP64 central directory of `valid.zip`: **43675 entries, 58 sequences**.

```
valid.zip
  SNGS-021/ ... SNGS-059/, SNGS-078/ ... SNGS-096/      # 58 dirs, non-contiguous ids
    Labels-GameState.json            # 15.9-29.3 MB uncompressed, one per sequence
    img1/
      000001.jpg ... 000750.jpg      # exactly 750 frames per sequence
```

There is **no** `gt/`, no `seqinfo.ini` and no `gameinfo.ini` in the GSR archive -
all of that information moved into `Labels-GameState.json`. (Those files belong to the
SoccerNet-**Tracking** MOT archives, section 5.)

Sequence directory names in `valid.zip`, exact:
`SNGS-021`..`SNGS-059` and `SNGS-078`..`SNGS-096`.

---

## 4. `Labels-GameState.json` schema

Top level, verified on two real files:

```
{"info": {...}, "images": [...], "annotations": [...], "categories": [...]}
```

`SNGS-056`: 750 images, 11599 annotations, 7 categories.
`SNGS-035`: 750 images, 13506 annotations, 7 categories.

### 4.1 `info`, real values from `SNGS-056`

```json
{
  "version": "1.3",
  "game_id": "3",
  "id": "056",
  "num_tracklets": "16",
  "action_position": "2232037",
  "action_class": "Goal",
  "visibility": "visible",
  "game_time_start": "2 - 36:48",
  "game_time_stop": "2 - 37:18",
  "clip_start": "2208000",
  "clip_stop": "2238000",
  "name": "SNGS-056",
  "im_dir": "img1",
  "frame_rate": 25,
  "seq_length": 750,
  "im_ext": ".jpg"
}
```

Types matter: **`frame_rate` and `seq_length` are JSON numbers; everything else in
`info` is a JSON string**, including `game_id`, `id`, `num_tracklets`,
`action_position`, `clip_start`, `clip_stop`.

* `game_time_start` / `game_time_stop` = `"<half> - <MM:SS>"`. Split on `" - "`:
  index 0 is the half (1 or 2) -> our `period`, index 1 is the clock -> our `t`.
  This is exactly what `tracklab` does
  (`info_data.get('game_time_start', ' - ').split(' - ')[1]`).
* `clip_start` / `clip_stop` are **milliseconds** into the half
  (`2238000 - 2208000 = 30000 ms = 30 s = 750 frames @ 25 fps`, consistent).
* `action_position` is also ms, and lies inside `[clip_start, clip_stop]`.
* `action_class` observed: `"Goal"`, `"Kick-off"`. `visibility` observed: `"visible"`.

### 4.2 `images[]`

```json
{
  "is_labeled": true,
  "image_id": "2056000001",
  "file_name": "000001.jpg",
  "height": 1080,
  "width": 1920,
  "has_labeled_person": true,
  "has_labeled_pitch": true,
  "has_labeled_camera": true,
  "ignore_regions_y": [],
  "ignore_regions_x": []
}
```

Exact key set (union over all 750 images, both sequences):
`file_name, has_labeled_camera, has_labeled_person, has_labeled_pitch, height,
ignore_regions_x, ignore_regions_y, image_id, is_labeled, width`.

`image_id` is a **10-character string**, layout `<split><seq><frame>`:

```
2  056  000001
^  ^    ^
|  |    +-- 6-digit 1-based frame number, matches file_name 000001.jpg
|  +------- 3-digit sequence id == info.id
+---------- 1-digit split id: 1=train 2=valid 3=test 4=challenge
```

(the split digit is `["train","valid","test","challenge"].index(split) + 1`, from
`sn-trackeval/trackeval/datasets/soccernet_gs.py`.)

Resolution is 1920x1080 throughout. `image_id.split('_')[-1]` is what upstream sorts
by, there is no `_` in these ids, so it degenerates to sorting by the full string,
which happens to be correct because the ids are zero-padded and fixed-width.

### 4.3 `annotations[]`

Three possible `supercategory` values are anticipated by upstream code:
`"object"`, `"pitch"`, `"camera"`. **Only `"object"` and `"pitch"` actually occur
in the 2025 valid split**, see gotchas.

Key sets measured:

| supercategory | keys |
|---|---|
| `object` | `attributes, bbox_image, bbox_pitch, bbox_pitch_raw, category_id, id, image_id, supercategory, track_id` |
| `pitch`  | `category_id, id, image_id, lines, supercategory` |

A real `object` annotation (`SNGS-056`, frame 1, verbatim):

```json
{
  "id": "2056000001",
  "image_id": "2056000001",
  "track_id": 1,
  "supercategory": "object",
  "category_id": 1,
  "attributes": {
    "role": "player",
    "jersey": "43",
    "team": "right"
  },
  "bbox_image": {
    "x": 1150,
    "y": 760,
    "x_center": 1181.5,
    "y_center": 845.0,
    "w": 63,
    "h": 170
  },
  "bbox_pitch": {
    "x_bottom_left": 34.35427429362302,
    "y_bottom_left": 16.713085240722055,
    "x_bottom_right": 34.87210848734805,
    "y_bottom_right": 17.09878027143052,
    "x_bottom_middle": 34.613191336985125,
    "y_bottom_middle": 16.905932716227866
  },
  "bbox_pitch_raw": {
    "x_bottom_left": 34.31780890162649,
    "y_bottom_left": 16.720244225853346,
    "x_bottom_right": 34.867602522413684,
    "y_bottom_right": 17.129743386053352,
    "x_bottom_middle": 34.59270561935637,
    "y_bottom_middle": 16.92499373693507
  }
}
```

* `track_id` is an **int** (not a string), 1-based, dense. Ranges measured:
  `SNGS-056` 1..16 (`num_tracklets` 16), `SNGS-035` 1..25 (`num_tracklets` 25).
  It is **sequence-local**, `SNGS-056` track 1 and `SNGS-035` track 1 are different
  people. `tracklab` builds a global id as
  `detections['track_id'].astype(str) + detections['video_id'].astype(str)`.
* `id` is a string and is unique across the whole file (11599/11599 unique in
  `SNGS-056`); it is *not* equal to `image_id` in general even though the first
  annotation happens to collide.
* `attributes` has exactly three keys: `role`, `jersey`, `team`.
  * `role` ∈ `{"player", "goalkeeper", "referee", "ball", "other"}`. `sn-trackeval`
    asserts `role in {"other","player","goalkeeper","referee"}` after dropping balls.
  * `team` ∈ `{"left", "right", null}`; `sn-trackeval` additionally tolerates the
    literal string `'nan'`. `null` for `referee`, `ball`, `other`.
  * `jersey` is a **string of digits or `null`** (e.g. `"43"`, `"5"`), never an int.
    `null` for goalkeepers whose number is not visible, and always for referee/ball.
    Observed distinct values in `SNGS-035`: `4,5,6,8,10,15,17,19,20,23,34`.
* `category_id` maps into `categories[]`: 1=player, 2=goalkeeper, 3=referee, 4=ball,
  5=pitch, 6=camera, 7=other.

### 4.4 `categories[]`

Verbatim (7 entries):

```json
[{"supercategory": "object", "id": 1, "name": "player"},
 {"supercategory": "object", "id": 2, "name": "goalkeeper"},
 {"supercategory": "object", "id": 3, "name": "referee"},
 {"supercategory": "object", "id": 4, "name": "ball"},
 {"supercategory": "pitch",  "id": 5, "name": "pitch", "lines": [ ...26 line names... ]},
 {"supercategory": "camera", "id": 6, "name": "camera"},
 {"supercategory": "object", "id": 7, "name": "other"}]
```

The 26 line names on category 5 are exactly `SoccerPitch.lines_classes` from
`plugins/calibration/sn_calibration_baseline/soccerpitch.py`:
`Big rect. left bottom/main/top`, `Big rect. right bottom/main/top`,
`Circle central/left/right`, `Goal left crossbar`, `Goal left post left/right`,
`Goal right crossbar`, `Goal right post left/right`, `Middle line`,
`Side line bottom/left/right/top`, `Small rect. left bottom/main/top`,
`Small rect. right bottom/main/top`.

### 4.5 `pitch` annotations

One per frame. `lines` is a **dict keyed by line name**, each value a list of
`{"x": float, "y": float}` points:

```json
{"id": "2056000016", "image_id": "2056000001", "supercategory": "pitch",
 "category_id": 5,
 "lines": {"Side line right": [{"x": 1.0, "y": 0.5673555676388917},
                               {"x": 0.907381467013889, "y": 0.5302988629765096}, ...],
           "Side line top":   [{"x": 0.0, "y": 0.23444351851851847}, ...]}}
```

**These are normalized *image* coordinates, not pitch coordinates.** Measured over
42684 points in `SNGS-035`: `x ∈ [-0.0000, 1.0000]`, `y ∈ [0.0641, 1.0041]`.
Multiply by `width`/`height` for pixels. Only the line classes visible in that frame
are present (12 keys in `SNGS-056` frame 1, 8 in `SNGS-035` frame 377).

---

## 5. Coordinate systems

### Image space (`bbox_image`)

Six keys: `x, y, x_center, y_center, w, h`. Pixels, origin at **image top-left**,
+y **down**, 1920x1080.

* `x, y` are the **top-left** corner (MOT `left, top`).
* Verified on all 10849 objects of `SNGS-056`: `x_center == x + w/2` and
  `y_center == y + h/2` hold exactly (0 violations).
* `x, y, w, h` are ints; `x_center, y_center` are floats (`.0` or `.5`).
* Measured ranges in `SNGS-056`: `x ∈ [0, 1495]`, `y ∈ [344, 1063]`,
  `w ∈ [6, 148]`, `h ∈ [8, 209]`.
* `tracklab` converts with
  `xywh_to_ltwh([bbox_image['x_center'], bbox_image['y_center'], bbox_image['w'], bbox_image['h']])`,
  i.e. it uses the centre keys, not `x`/`y`. Either works.

### Pitch space (`bbox_pitch`, `bbox_pitch_raw`)

Six keys: `x_bottom_left, y_bottom_left, x_bottom_middle, y_bottom_middle,
x_bottom_right, y_bottom_right`. These are the three points along the **bottom edge**
of the image bbox, unprojected onto the pitch plane Z=0.
For sportio, the player position is `(x_bottom_middle, y_bottom_middle)`.

* **Units: metres.** Confirmed three independent ways:
  1. `sn-trackeval` `'EVAL_DIST_TOL': 5,  # ... in meters`, and the sn-gamestate
     README: "a special distance tolerance parameter τ set to 5 meters".
  2. `sn_gamestate/visualization/pitch.py` draws the radar with
     `pitch_width = 105 + 2*10`, `pitch_height = 68 + 2*5` and plots each detection at
     `radar_center + int(x_bottom_middle * scale)`, a bare metre-to-pixel scale.
  3. Measured values: `SNGS-056` (a goal at the right end)
     `x_bottom_middle ∈ [28.97, 57.64]`, `y_bottom_middle ∈ [-10.44, 17.57]`;
     goalkeeper x clusters at `[49.55, 52.47]` i.e. right on the 52.5 m goal line.
* **Origin: pitch centre.** `SoccerPitch` puts the left penalty mark at
  `[-pitch_length/2 + 11, 0, 0]` and the right at `[+pitch_length/2 - 11, 0, 0]`.
  Confirmed by the goalkeeper clustering at x≈52.0 in `SNGS-056`.
* **Pitch dimensions: 105 x 68 m**, `SoccerPitch.__init__(self, pitch_length=105., pitch_width=68.)`.
  So on-pitch `x ∈ [-52.5, +52.5]` (goal-to-goal) and `y ∈ [-34, +34]` (touchline to
  touchline). Other constants: `GOAL_LINE_TO_PENALTY_MARK=11.0`,
  `PENALTY_AREA_WIDTH=40.32`, `PENALTY_AREA_LENGTH=16.5`, `GOAL_AREA_WIDTH=18.32`,
  `GOAL_AREA_LENGTH=5.5`, `CENTER_CIRCLE_RADIUS=9.15`, `GOAL_HEIGHT=2.44`,
  `GOAL_LENGTH=7.32`.
* **+y direction:** the radar draws at `radar_center_y + y_bottom_middle*scale`, and
  image y grows downward, so **+y points toward the bottom touchline as seen in the
  broadcast frame**. sportio's canonical y is up-positive, so `y_sportio = -y_pitch`
  (or flip once and stay consistent, the important part is that it is *not* already
  up-positive).
* No rescaling is needed for sportio: SoccerNet is *already* 105x68 metres centred at
  the origin. Only `+52.5/+34` shift and y-sign need handling.
* `bbox_pitch` vs `bbox_pitch_raw`: `bbox_pitch` is the temporally smoothed version
  introduced in dataset **v1.3** ("Temporal consistency improvement of bbox pitch
  athlete location"); `bbox_pitch_raw` is the per-frame unprojection. **Use
  `bbox_pitch`.** Both are present on every object annotation in v1.3.

### Time

* `frame_rate` = **25** (both sequences, and it is a JSON int).
* `seq_length` = **750** frames = **30.0 s** per clip.
* Frame numbering in `file_name` and in the last 6 digits of `image_id` is **1-based**
  (`000001.jpg` .. `000750.jpg`).
* 25 fps > the 10 Hz minimum sportio wants for `tracking`, so no interpolation needed;
  downsample by 2 or 5 if desired (`frame % 5 == 1` gives 5 Hz, keep all for 25 Hz).
* Absolute clock: `t_abs_ms = clip_start + (frame - 1) * 1000 / frame_rate`, and
  `period` = `int(game_time_start.split(' - ')[0])`.
  Cross-check on `SNGS-056`: `clip_start=2208000` ms = 36:48.0 into half 2, which is
  exactly `game_time_start = "2 - 36:48"`. Good.

---

## 6. SoccerNet-Tracking (MOT) on-disk format, gated, documented from source

Could not be downloaded (NDA). Documented from upstream code and README, which is
enough to write a loader; see the citation table in section 8.

Directory layout per sequence (MOTChallenge/MOT20 convention as used by
`tracklab/wrappers/dataset/soccernet/soccernet_mot.py`):

```
<split>/
  SNMOT-116/
    img1/
      000001.jpg ... 000750.jpg        # {i:06d}.jpg, 1-based
    gt/
      gt.txt                           # ground truth, MOT 10-column CSV
    det/
      det.txt                          # public detections (challenge splits)
    seqinfo.ini
    gameinfo.ini
```

Sequence names are `SNMOT-###`. Exact lists ship inside the pip package at
`SoccerNet/data/SNMOT-test.txt` (49 sequences, `SNMOT-116`..), 
`SoccerNet/data/SNMOT-challenge.txt` (58, `SNMOT-021`..) and
`SoccerNet/data/SNMOT-challenge-nodet.txt` (36, `SNMOT-001`..). Each file has a
`name` header line then one id per line.

### `gt/gt.txt`, 10 columns, no header

From the sn-tracking README, verbatim:

> The ground truth and detections are stored in comma-separate csv files with 10 columns.
> These values correspond in order to: frame ID, track ID, top left coordinate of the
> bounding box, top y coordinate, width, height, confidence score for the detection
> (always 1. for the ground truth) and the remaining values are set to -1 as they are
> not used in our dataset, but are needed to comply with the MOT20 requirements.

`tracklab`'s reader names them:

```python
columns = ['image_id', 'track_id', 'left', 'top', 'width', 'height',
           'bbox_conf', 'class', 'visibility', 'unused']
df = pd.read_csv(file_path, header=None, names=columns)
```

So: `frame, track_id, bbox_left, bbox_top, bbox_width, bbox_height, conf, class,
visibility, unused`, where `conf == 1` in GT and columns 8/9/10 (`class`,
`visibility`, `unused`) are **always `-1`**, SoccerNet does not populate them, unlike
stock MOT20. `frame` is 1-based; `tracklab` rebases with `detections_df['image_id'] - 1`.
Coordinates are pixels, image top-left origin, 1920x1080.

### `seqinfo.ini`

Keys `tracklab` actually reads: `seqLength`, `frameRate`, `imWidth`, `imHeight`.
The remaining keys are the MOTChallenge standard (`name`, `imDir`, `imExt`).
Format is `key=value`, one per line, under a single section header line.

### `gameinfo.ini`

Keys `tracklab` reads, exact spelling (note the mixed camelCase / snake_case):

```
name, game_id, gameTimeStart, gameTimeStop, clipStart, clipStop,
actionPosition, actionClass, visibility, num_tracklets, trackletID_<i>
```

`gameTimeStart`/`gameTimeStop` use the same `"<half> - <MM:SS>"` encoding as the GSR
`info` block. `trackletID_<i>` for `i` in `1..num_tracklets` and encodes the identity
of MOT track `i`:

```python
role, additional_info = tracklet_entry.split(';')
role = role.strip().replace(' ', '_')
additional_info = additional_info.replace(' ', '_')
if "goalkeeper" in role:  team = "left" if "left" in role else "right"; jersey = int(additional_info) if additional_info.isdigit() else None
elif "player" in role:    team = "left" if "left" in role else "right"; jersey = int(additional_info) if additional_info.isdigit() else None
elif "referee" in role:   team = None; jersey = None; position = additional_info
elif "ball" in role:      team = None; jersey = None
else:                     assert "other" in role
```

So the value is `"<role phrase>; <extra>"` where the role phrase contains the literal
substrings `player`/`goalkeeper`/`referee`/`ball`/`other` and, for players and
goalkeepers, `left` or `right`. The extra field is the jersey number for
players/goalkeepers and a free-text position for referees.

This is the **only** place team/role/jersey live in the MOT product, `gt.txt` itself
carries no identity, so `gameinfo.ini` must be joined on `track_id`.

---

## 7. Gotchas that will break a naive loader

1. **`"bbox_pitch": null` is common and can cover half a clip.** In `SNGS-035`,
   **5975 of 12756** object annotations (47%) have `bbox_pitch == null`, and it is not
   scattered, frames `2035000377` through `2035000750` (374 consecutive frames, the
   entire back half of the clip) have `bbox_pitch == null` on *every* object. Cause:
   camera calibration is lost mid-clip. `SNGS-056` by contrast has 0 nulls.
   `bbox_pitch_raw` is null on essentially the same rows (6008 vs 5975).
   *A loader that does `ann["bbox_pitch"]["x_bottom_middle"]` will crash on the
   second file in the dataset.*
2. **`images[].has_labeled_camera` is a near-but-not-exact proxy for that.** In
   `SNGS-035`, 376 frames have `has_labeled_camera == false` but only 374 frames are
   all-null; frames `2035000165` and `2035000365` have `has_labeled_camera == false`
   yet full `bbox_pitch` data. Test `bbox_pitch is None` per annotation; do not
   pre-filter on the flag.
3. **`sn-trackeval` silently drops frames.** It keeps only images where
   `has_labeled_pitch and has_labeled_camera and has_labeled_person` are all true. For
   `SNGS-035` that is 374 of 750 frames. If you compare your row counts to the
   official evaluator's, this is why they differ.
4. **Pitch coordinates blow up near the horizon.** Unprojection is unbounded, so
   `SNGS-035` contains `x_bottom_middle = -175.59` and `y_bottom_middle = -280.39`
, far outside a 105x68 pitch. Upstream's own visualiser does
   `np.clip(..., -10000, 10000)`. Measured: 99.7% of `SNGS-035` and 100.0% of
   `SNGS-056` non-null points fall inside pitch + 5 m margin, so clip or drop the tail.
5. **No `camera` annotations are actually shipped.** `categories` declares id 6
   `"camera"` and both `sn-trackeval` and `tracklab` have code paths for
   `supercategory == "camera"` with a `parameters` field, but in the 2025 valid split
   the only supercategories present are `object` and `pitch` (verified on both
   sequences; no annotation anywhere contains a `parameters` key). Camera parameters
   are something a *predictor* emits, not something the GT provides. Do not build the
   loader around them.
6. **`team` is `"left"`/`"right"` relative to the camera, not a club id, and not
   recoverable from x.** The README says "team affiliation (i.e. left or right w.r.t.
   the camera viewpoint)". Measured in `SNGS-035` (a kick-off, so both teams near the
   centre circle): mean `x_bottom_middle` is `-9.49` for team `left` and `+0.00` for
   team `right`; medians `-8.28` vs `+0.18`. The two are **not** separated by the
   halfway line. Consequences for sportio: `team` maps to `home`/`away` only by
   convention, and **attacking direction is not derivable from a 30 s clip**, there
   are no goal/possession events in the annotations to anchor it. Record the raw
   `left`/`right` label and leave direction normalisation to the caller.
7. **Sequence ids are non-contiguous.** `valid.zip` has `SNGS-021..059` then
   `SNGS-078..096`; there is no `SNGS-060..077`. Do not `range()` over ids.
8. **Everything in `info` except `frame_rate`/`seq_length` is a string**, including
   numeric-looking fields. `attributes.jersey` is a string too. `track_id` is an int.
   Mixed typing across the same file.
9. **`tracklab`'s `read_ini_file` is fragile**, `dict(line.strip().split('=') for line
   in lines[1:])` unconditionally drops the first line and raises `ValueError` on a
   blank line or a value containing `=`. Do not copy it; use `configparser` or a
   tolerant split.
10. **`tracklab`'s `trackletID` jersey parse loses numbers when there is a space after
    the `;`.** It applies `.replace(' ', '_')` before `.isdigit()`, so
    `"player team left; 10"` yields `additional_info == "_10"`, `.isdigit()` is
    `False`, `jersey_number = None`. Since the exact spacing in the real (gated)
    `gameinfo.ini` is not publicly documented, a sportio loader should `.strip()`
    before `int()` so it works either way.
11. **`sn-trackeval` accepts `team == 'nan'`** as a literal string alongside
    `"left"`/`"right"`/`null`. Not observed in the two sequences read, but guard for it.
12. **Sequence-local ids.** `track_id`, and the `<seq>` digits inside `image_id`, are
    only unique within a sequence. Namespace with the sequence name when building
    sportio's `player_id` / `match_id`.
13. **A GSR clip is 30 s of one match, not a match.** `info.game_id` ("3", "2") is a
    SoccerNet game index, and several `SNGS-*` clips can share one `game_id`. If
    sportio's `match_id` should mean a match, derive it from `game_id`; if it should
    mean a loadable unit, use the sequence name.
14. **11.2 GB per split, and the annotations are 2-4 MB compressed inside it.** Do not
    make a "just download it" code path the default. Range requests work
    (`accept-ranges: bytes`), so the JSON can be pulled without the JPEGs.

### Mapping onto sportio's canonical `tracking` frame

SoccerNet GSR is a *tracking* source, not an *events* source, there is nothing in
`Labels-GameState.json` that maps to sportio's `events` schema (no passes, shots,
outcomes; only `info.action_class` labels the whole clip). Suggested mapping:

| sportio | from |
|---|---|
| `match_id` | `info.name` (e.g. `"SNGS-056"`), or `info.game_id` if you want real matches |
| `frame` | last 6 digits of `image_id`, 1-based |
| `t` | `(frame - 1) / info.frame_rate`, plus `clip_start/1000` for half-relative time |
| `period` | `int(info.game_time_start.split(' - ')[0])` |
| `team` | `attributes.team` -> `"left"`/`"right"` -> home/away by convention; `"ball"` when `attributes.role == "ball"` |
| `player_id` | `f"{info.name}-{track_id}"` |
| `jersey` | `attributes.jersey` (str or None -> int or None) |
| `x` | `bbox_pitch.x_bottom_middle + 52.5` |
| `y` | `34.0 - bbox_pitch.y_bottom_middle` (flip to y-up) |
| `vx`, `vy` | not provided; differentiate x/y over `frame` |
| `confidence` | not provided in GT (upstream defaults it to 1); use 1.0, or None |

---

## 8. Fixtures in this repo

### `tests/fixtures/soccernet/gsr/`, REAL

Genuine slices of `SoccerNet/SN-GSR-2025` `valid.zip`
(commit `ce84ee7d9acb2f9fe999ceed2b38e303ffa5efb9`, `info.version == "1.3"`),
obtained by ZIP64 range requests. Only `info.seq_length` was edited (750 -> 3).

| file | size | content |
|---|---|---|
| `gsr/SNGS-056/Labels-GameState.json` | 59 KB | frames `2056000001..003`, 45 object + 3 pitch annotations, **0 null `bbox_pitch`** |
| `gsr/SNGS-035/Labels-GameState.json` | 41 KB | frames `2035000376..378`, 48 object + 3 pitch annotations, **32 of 48 with `"bbox_pitch": null`**, deliberately straddles the calibration loss at frame 377 |

### `tests/fixtures/soccernet/mot/SNMOT-116/`, SYNTHETIC but schema-faithful

SoccerNet-Tracking is NDA-gated, so these were **hand-written**. The numbers are
invented (loosely traced from the real GSR bboxes above); every *key name, column
order and value format* comes from a verified source:

| fixture element | field names taken from |
|---|---|
| `gt/gt.txt` 10-column layout, `conf=1`, trailing `-1,-1,-1` | sn-tracking `README.md` "Data format" section (quoted in §6) + `tracklab/wrappers/dataset/soccernet/soccernet_mot.py::read_motchallenge_formatted_file` column list |
| `seqinfo.ini` keys `seqLength, frameRate, imWidth, imHeight` | `soccernet_mot.py::load_set` (`seqinfo_data.get('seqLength')` etc.) |
| `seqinfo.ini` keys `name, imDir, imExt` | MOTChallenge/MOT20 standard, corroborated by the GSR `info` block which carries the same three as `name`, `im_dir`, `im_ext` |
| `gameinfo.ini` keys `name, game_id, gameTimeStart, gameTimeStop, clipStart, clipStop, actionPosition, actionClass, visibility, num_tracklets, trackletID_<i>` | `soccernet_mot.py::load_set`, exact `gameinfo_data.get(...)` spellings |
| `trackletID_<i>` value grammar `"<role phrase>; <extra>"` with `left`/`right` inside the role phrase | `soccernet_mot.py::load_set` tracklet parsing block (quoted in §6) |
| `frameRate=25`, `seqLength=750`, `imWidth=1920`, `imHeight=1080` | measured from the real GSR `info` and `images` blocks (same source footage, 30 s clips) |
| `gameTimeStart`/`Stop`, `clipStart`/`Stop`, `actionPosition`, `actionClass` values | copied from the real `SNGS-056` `info` block so the encodings are genuine |
| section header line `[Sequence]` | **assumption.** `read_ini_file` discards `lines[0]` unconditionally, so upstream requires *a* header but never names it; `[Sequence]` is the MOTChallenge convention |

The one genuinely uncertain detail is the whitespace after `;` in `trackletID_<i>` -
see gotcha 10.

---

## 9. Sources read

| what | URL |
|---|---|
| PyPI metadata | `https://pypi.org/pypi/SoccerNet/json` |
| `SoccerNet` 0.1.62 sdist (`Downloader.py`, `Evaluation/GameStateReconstruction.py`, `data/SNMOT-*.txt`) | `https://files.pythonhosted.org/packages/e8/c8/.../soccernet-0.1.62.tar.gz` |
| sn-gamestate README | `https://raw.githubusercontent.com/SoccerNet/sn-gamestate/main/README.md` |
| bbox -> pitch unprojection | `https://raw.githubusercontent.com/SoccerNet/sn-gamestate/main/sn_gamestate/calibration/bbox2pitch.py` |
| pitch constants | `https://raw.githubusercontent.com/SoccerNet/sn-gamestate/main/plugins/calibration/sn_calibration_baseline/soccerpitch.py` |
| radar/metre scale | `https://raw.githubusercontent.com/SoccerNet/sn-gamestate/main/sn_gamestate/visualization/pitch.py` |
| GSR GT parser (authoritative for JSON field names) | `https://raw.githubusercontent.com/SoccerNet/sn-trackeval/master/trackeval/datasets/soccernet_gs.py` |
| GSR dataset loader | `https://raw.githubusercontent.com/TrackingLaboratory/tracklab/main/tracklab/wrappers/dataset/soccernet/soccernet_game_state.py` |
| MOT dataset loader (authoritative for `gt.txt` / `*.ini`) | `https://raw.githubusercontent.com/TrackingLaboratory/tracklab/main/tracklab/wrappers/dataset/soccernet/soccernet_mot.py` |
| sn-tracking README | `https://raw.githubusercontent.com/SoccerNet/sn-tracking/main/README.md` |
| HF dataset metadata | `https://huggingface.co/api/datasets/SoccerNet/SN-GSR-2025` |
| real GSR annotations | `https://huggingface.co/datasets/SoccerNet/SN-GSR-2025/resolve/main/valid.zip` (range requests) |

Cached copies of all of the above are under
`data/raw/soccernet/` (gitignored), including the full 21 MB
`SNGS-056_Labels-GameState.json` and 19 MB `SNGS-035_Labels-GameState.json`,
and `valid_zip_entries.json` (the parsed 43675-entry central directory).
