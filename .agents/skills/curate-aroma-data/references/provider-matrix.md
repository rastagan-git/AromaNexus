# Provider matrix

Review these notes before choosing or running a provider. Access policies can change; re-check the linked official page when a live run or redistribution decision matters.

| Provider | Best use | Access behavior | Rights and scientific caveat |
| --- | --- | --- | --- |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) and [PUG-View](https://pubchem.ncbi.nlm.nih.gov/docs/pug-view) | CID, InChIKey, structures, formula, properties, sourced odor annotations | Live API, cached locally, below the official five-requests-per-second ceiling, bounded retries | PubChem aggregates contributor records. Preserve contributor source, URL, and license URL for annotation text. |
| [NIST Chemistry WebBook](https://webbook.nist.gov/chemistry/) | Existing GC retention-index and name-to-CAS workflows | Cached HTML, at least five seconds between uncached requests per [robots.txt](https://webbook.nist.gov/robots.txt) | NIST SRD compilation rights apply. Fetch on demand and cite; do not redistribute a bulk scrape. |
| [Pyrfume Public Data Archive](https://github.com/pyrfume/pyrfume-data) | Curated odor descriptors or collection membership keyed by PubChem CID | Pinned GitHub snapshot; explicit archive allowlist; files cached locally | The repository code is MIT, but manifests record upstream rights and sometimes copyright caveats. Do not treat every archive as MIT-licensed data. |
| [M2OR](https://github.com/chemosim-lab/M2OR) | Molecule-olfactory-receptor pairs, species, responsive assays, and study DOI | Optional pinned CSV download (about 43 MB), cached locally | Dataset repository is Apache-2.0. Results are assay evidence, not human odor perception or clinical prediction. |
| [MFFI](https://mffi.sjtu.edu.cn/database/search) | Chinese/English names, sensory characteristics, and water thresholds | Interactive Selenium browser, conservative pacing | No public API, rate policy, or reuse license was found. Robots allowance is not a data license; use conservatively and cite. |
| [ChemicalBook](https://www.chemicalbook.com/) | Original odor/threshold/type compatibility path only | Disabled until explicit permission confirmation; visible manual browser | Current [robots.txt](https://www.chemicalbook.com/robots.txt) excludes the search and product-property routes. Never bypass CAPTCHA or imply permission. |

Avoid automated extraction from FlavorDB2, Flavornet, Good Scents, VCF, or other attractive-but-undocumented sites unless an official API, bulk download, or written permission clearly covers the intended use.
