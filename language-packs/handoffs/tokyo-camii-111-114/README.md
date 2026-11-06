# Tokyo Camii Japanese reader: chapters 111–114 only

The current local app offers the source-bound Tokyo Camii reading for **111:1–114:6 only**: four complete chapters and 20 verses. This is not full Japanese Quran coverage. Outside that range the reader reports unavailability. Tokyo Camii remains the default; Sato remains a separate option and its text is unavailable in this integration.

The reader retains the published chapter introductions, basmalas, notes, ruby and attribution. Its source display shows the publication credits; technical source files and proof images are not linked in ordinary reading. The existing source-bound adapter validates its 17 companion files for offline integrity, so those files remain in the local runtime. The reader does not substitute another edition or generated text.

This handoff contains the exact installed [view script](tokyo20-app267.js) and [source-bound adapter](tokyo20-adapter267.js). It is not a standalone app and does not republish the publisher's Quran text. It requires the existing model, source-byte bundle, 17 source companions and application hooks. The recorded permission covers the app/offline delivery; third-party text retains its own terms.

The local runtime is `app-7ada0af4302b14fb8670`, fingerprint `7ada0af4302b14fb86704f97ee4f745262f030bab0f95db7b1628569d169ec1d`, manifest SHA-256 `d3cda44cdbc505704611e06f99cfe995874ac20d1b13672fefa8f8d4c9f7d1cd`. SHA-256: view script `3c467e3cc44c98fcf7f6d523543104610ba565cb7764254ed20e4e837ec633ea`; adapter `d2d1d759f0539a11400c23319f4009c71ae8b5ea4f195b8a2dc6f5ff4940eb94`. The app's view script and three entry pages use the corresponding short hashes for cache versioning. Validate an existing app baseline and all source conditions before reuse.

All 20 verse readings and ordered chapter parts were compared against the source-bound model in offline phone and tablet browser layouts. Tests covered notes, source integrity, Sato selection, unavailability outside the scope, the four other held locales, and preservation of current Seerah content. The candidate was also checked online. The successor runtime adds a separate An-Nisa source-view cleanup; the Tokyo view and adapter are unchanged and were retested on the successor in an offline phone browser. These checks do not constitute a physical-device test or website deployment.

Publisher: Tokyo Camii Publishing, edition 01_03, 2022-02-01, ISBN 978-4-910474-00-7. [Publisher information](https://institute.tokyocamii.org/ja/2024/09/quran-japanese-comprehension/).
