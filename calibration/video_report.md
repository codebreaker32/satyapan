# Video detector calibration report

Model: `GenD_CLIP_L_14@891ce01`. Manifest: `video_manifest.csv`, 138 clips.

Thresholds are set on real clips only. Catch rate = share of fake clips at or above the threshold.

Each cell is calibrated on its own clips; a kind of video with no cell here makes the detector abstain.
Catch rates count only fakes the detector judged; 'Fakes abstained' are the ones it declined to judge.

| Cell | Usable real | Usable fake | Fakes abstained | t_fpr20 | t_fpr5 | t_fpr1 | Catch at 5% FPR | Catch at 20% FPR | AUC |
|---|---|---|---|---|---|---|---|---|---|
| video/hd | 38 | 2 | 0 | 0.487 | 0.923 | - | 0.500 | 1.000 | 0.974 |
| video/sd | 26 | 6 | 2 | 0.712 | 0.971 | - | 0.000 | 0.833 | 0.872 |

## Clips the detector declined to judge (not used for thresholds)

- the frames disagree with each other: 24
- the face is too small to judge (under 80 px): 21
- a usable face was visible in too few frames: 21

With few real clips these thresholds are coarse; the counts above say how much to trust them.

## What this means (read before quoting any number)

- **HD video (short side above 480 px):** genuine faces mostly score low (median about 0.2), and the two face-swaps
  score 0.80 and 0.95. Separation is good (AUC 0.97 on 38 genuine and 2 fake clips). At the 5% false-alarm threshold
  (0.92) the detector flags a clear face swap; with only 2 fakes, the catch rate is anecdotal, not a measurement.
- **WhatsApp-size video (480 px or less):** compression makes some genuine faces score as high as fakes (four genuine
  clips at 0.94 to 0.97, all heavily compressed interviews). The 5% false-alarm threshold therefore sits at 0.97, and
  none of the 6 face swaps clears it. In practice the face check rarely flags a WhatsApp forward; it says "no signs"
  or "unsure". It still ranks fakes above genuine clips more often than not (AUC 0.87).
- **Declining is common on real-world footage:** 66 of 138 clips were not judged (frames disagree, face too small, or
  a face in too few frames). Interviews cut between people and cameras; the detector abstains rather than guess.
- **How it counts (`docs/design-decisions.md`):** a face flag is "moderate" (70%) at most,
  because there is no 1% line with this few genuine clips, so alone it gives 35%: AMBER. Before the merge: it could raise a case to AMBER, and it could be the
  second, independent check behind a cited issuer rule. Open detectors lose about half their accuracy on deepfakes
  circulated in 2024 (Deepfake-Eval-2024); these numbers are consistent with that, which is why Satyapan checks the
  instruction first.
- **Sample sizes:** genuine 38 (HD) and 26 (SD); fakes 2 and 6, from one vendor sample. More fakes (Deepfake-Eval-2024,
  if access is approved) would turn the catch rates into measurements.

## Are the false alarms just small faces? No.

Checked through the running service on 24 Oct: the genuine clips that score highest have large faces. One WhatsApp-
size interview scores 0.971 with a 161 px face, an HD interview 0.924 with 131 px, and another 0.915 with 231 px,
while a correctly cleared genuine clip has a 124 px face. A stricter face-size gate would therefore not remove these
false alarms; they depend on the footage itself (webcam lighting, heavy compression), the in-the-wild weakness that
Deepfake-Eval-2024 documents. The 5% thresholds mean about one genuine clip in twenty is flagged by design, which is
why a face flag counts only through its calibrated band, and alone gives at most AMBER.
