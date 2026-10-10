# Data provenance and license

The primary source is ShanghaiT2DM, from the Shanghai diabetes datasets:

- Zhao et al., *A publicly available dataset of continuous glucose monitoring records in patients with diabetes*, Scientific Data 10, 35 (2023). https://www.nature.com/articles/s41597-023-01940-7
- Public archive: https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933
- Figshare metadata API: https://api.figshare.com/v2/articles/21600933
- Source license: Creative Commons Attribution 4.0 International (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/

Attribution should accompany reuse of raw recordings, normalized observations and model-training artifacts. The preparation manifest records archive version, hash, source file identity, counts and transformation decisions. This project changes source formatting, normalizes patient identifiers/timestamps, and selects baseline context; it does not represent the source creators' endorsement.

Only already-anonymized public research recordings are used. Patient labels retain anonymized source identifiers. Recordings are not live sensors. The Chinese cohort does not establish generalization to Indian patients or clinical settings.

CGMacros is not included in this first build. Its CC BY-NC-SA terms differ from Shanghai's and require separate handling before any future inclusion.

The MIT license applies to application code. Third-party packages retain their own licenses. Do not remove this attribution when sharing the project.
