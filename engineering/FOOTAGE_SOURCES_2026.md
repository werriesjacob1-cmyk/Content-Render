# Content Render footage source review

Reviewed November 20, 2026. Ranking reflects relevance potential, licensing clarity, and suitability for unattended retrieval. Latency estimates below are request budgets or published hardware measurements. None is a provider SLA. For landscape archives, 9:16 suitability depends on whether the subject survives a center crop.

## Video

| Rank and source | Cost, unattended access, and rights | Orientation, latency, and likely failure |
| --- | --- | --- |
| 1. [Wikimedia Commons](https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy) | Keyless Action API with identified client and bounded requests. [Imageinfo](https://www.mediawiki.org/wiki/API%3AImageinfo/en) supplies per-file metadata. Accept explicit CC0, public domain mark, or CC-BY with credit. | Variable orientation. One request budgeted at 5 s. Long masters, incomplete license metadata, third-party uploads, and captions that crop poorly reduce usable coverage. |
| 2. [Library of Congress](https://www.loc.gov/apis/json-and-yaml/) | Keyless, rate-limited JSON API for programmatic access. The [National Screening Room](https://www.loc.gov/collections/national-screening-room/about-this-collection/) mixes public-domain and copyrighted films. Require explicit item rights and a direct, size-bounded MP4 from [item resources](https://www.loc.gov/apis/json-and-yaml/responses/item-and-resource/). | Mostly landscape historical material. Search budget 4 s followed by at most three item calls at 3 s each. Free download and “no known restrictions” are insufficient. Observed HTTP 403 in a direct probe and timeout during a smoke evaluation. |
| 3. [NASA Scientific Visualization Studio](https://svs.gsfc.nasa.gov/help/) | Keyless search and page APIs. Public-domain studio material has exceptions. Require an explicit public-domain field in the adapter and use video without original audio. | Useful for visible physical mechanisms. Landscape is common, short portrait crops need QA. Requests budgeted at 3 s each. Strict filter may remove otherwise usable clips. Timeout observed on a direct page API probe. |
| 4. [Pexels](https://www.pexels.com/api/documentation/) | Existing free API key, 200 requests/hour and 20,000/month by default. [Pexels license](https://www.pexels.com/license/) permits free use. API documentation requests linking and credit, which the selector now records. | Native portrait filter. General stock is plentiful but often too generic for scientific claims. No keyed calls made for this audit. |
| 5. [NOAA Ocean Exploration](https://oceanexplorer.noaa.gov/data/access/) | Public [archive and API](https://www.ncei.noaa.gov/access/ocean-exploration/video/). [Rights depend on the contributing source and caption](https://oceanexplorer.noaa.gov/about/media-kit/). No quoted per-call fee or verified production request quota. | High potential deep-sea value. Landscape ROV footage, dark images, long archives and partner credits. Deferred pending a tested item-to-credit binding and bounded clip retrieval. |
| 6. [USGS](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) | Public USGS-produced material has third-party and likeness exceptions. A media-search endpoint with reliable item-level rights and an unattended quota was not established. | Useful geology and field photos; landscape is likely. Deferred. |
| 7. [Europeana](https://apis.europeana.eu/) | Programmatic search with an API key. [Rights statements](https://pro.europeana.eu/page/available-rights-statements) differ by collection and item. A usable quota and downstream media-host access were not verified. | Variable orientation and latency. Deferred due to mixed licenses and provider-specific media links. |
| Other | [Internet Archive](https://archive.org/developers/md-read.html) exposes item metadata, but existing download selection does not prove rights for the chosen file. [ESA](https://www.esa.int/pl/terms-and-conditions/terms-and-conditions-for-images-and-videos) has purpose-specific terms and on-screen video credit requirements. Pixabay was excluded by the project mandate. The current Coverr and NASA Images adapters lack per-asset evidence in their results. | Excluded from live selection in this patch. Archives of unknown rights can be reconsidered once the selected files carry explicit permitted terms. |

## Scientific imagery

| Source | Decision |
| --- | --- |
| [RCSB PDB](https://www.rcsb.org/pages/usage-policy) | Programmatic data and structure-summary images are CC0. Use a named PDB accession to bind a scene to the original structure; record depositor credit and entry URL. Square depiction with local motion is usable in a portrait canvas. Missing assembly depictions fall through. No per-call fee or sustained rate verified. |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) | Free programmatic structure access is promising. Existing helper returns the resolved name after a download but does not prove the exact output asset license and record link. Deferred from the production path. |
| [Smithsonian Open Access](https://www.si.edu/openaccess/faq) | Explicitly CC0 assets qualify. Public collections API requires a registered key. The separate [3D API](https://3d-api.si.edu/api-docs/) is alpha. Better candidate for future archival stills and 3D objects than general video. Unmeasured latency and key/coverage requirements make it a lower priority. |
| [HHMI BioInteractive](https://www.hhmi.org/terms-of-use) | Commercial reuse generally requires permission unless the individual license permits it. Reject generic ingestion. |
| [CERN Open Data](https://opendata.cern.ch/docs/faq) and NIH | Open scientific datasets do not establish rights to an adjacent video or diagram. No media endpoint with consistently machine-readable output rights and verified CI access was established. NASA SVS, RCSB, Commons and source-checked archival stills are stronger candidates for this change. |

## AI video and stills

| Candidate | Cost and limits | Decision |
| --- | --- | --- |
| [Legacy fal LTX Video](https://fal.ai/models/fal-ai/ltx-video) | Advertised at $0.02/video against the existing account credit and request cap. The older endpoint already appears in the bakeoff. | Keep as the compatibility baseline with existing relevance and pseudo-text rejection. The cap now counts attempted calls even when no usable asset is returned. [fal output terms](https://fal.ai/legal/terms-of-service) apply. |
| [fal LTX-2.3 Fast](https://fal.ai/models/fal-ai/ltx-2.3/text-to-video/fast) | 9:16 supported. The landing page disagrees with itself at 1080p ($0.04 versus $0.06/s), so budget at $0.24–$0.36 per 6-second clip. Already in `video_model_bakeoff.py`. | No matched scene bakeoff established a relevance or pseudo-text improvement for the additional spend. Latency and account-specific rate limits were unverified. No default switch. [API schema](https://fal.ai/models/fal-ai/ltx-2.3/text-to-video/fast/api) · [Output terms](https://fal.ai/legal/terms-of-service) |
| [Wan2.2 weights](https://github.com/Wan-Video/Wan2.2) | Apache 2.0 weights. Upstream 5B quickstart calls for 24 GB GPU VRAM and documents an example 5-second 720p clip. Standard [GitHub-hosted runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) lacks that GPU. | Reject for ordinary CI. Weight license is separate from evidence about specific hosted outputs. Portrait, visual relevance, and text quality were unmeasured. |
| [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/pricing) | Free-user monthly credit is $0.10, subject to change. Cost, output rights, clip length, latency, dimensions and rate limits depend on the routed provider. | No dependable recurring free-video quota established. No provider or key added. |
| [Pollinations](https://gen.pollinations.ai/docs) | API documentation now includes model-dependent pricing and payment paths. The existing image integration supports local Ken Burns after download. | Deferred from the live selector. Free balance, specific output rights, and unattended account behavior were not verified. Paid Imagen fallback also removed from the live selector. |
| Local evidence-bound motion | Zero provider usage. Project-created 9:16 graphics, rendered with existing FFmpeg and the scene's audio. | Preferred for verified process-flow plans. Scale remains gated by existing semantic comparability rules. A 4-second synthetic-audio process graphic was rendered locally and a frame inspected. |

## Before and after source evidence

The manual script reports title-token overlap, not vision relevance. It returns null for hit rate when a source errors. License pass rate on returned candidates measures only the post-filter set. A zero-result query has no relevance or license denominator.

| Measurement | Before | After |
| --- | --- | --- |
| Zero-quota pipeline (rebased baseline) | `RESULT: 1639 passed, 0 failed` | `RESULT: 1639 passed, 0 failed` |
| Production selection | First source returning any candidates could mask later sources. | Licensed scientific and archival results compete with portrait stock. Verified process flow can bypass footage. |
| Commons discovery | Paired footage baseline unavailable. | 14 of 88 distinct queries returned candidates. Median title overlap was 0.417. All 24 returned assets passed the filter, whose rejected-result denominator is not instrumented. |
| Library of Congress discovery | Source absent. | Timeout stopped the evaluation. Hit rate and relevance are unknown. Opt-in via `FOOTAGE_CONGRESS_ENABLED=1`. |
| NASA SVS discovery | Source absent. | Zero eligible results across 88 distinct queries under the strict filter. Opt-in via `FOOTAGE_SVS_ENABLED=1`. |

The evaluation provides retrieval evidence. Finished-video relevance and variety have no paired before/after measurement. The standard legacy manifest lane does not emit the sealed Writer sidecars used by deterministic graphics, so that route activates only for evidence-bearing manifests.

Run `python scripts/evaluate_footage_sources.py` for archived-source retrieval, or add `--source pexels` when an existing key is available. The evaluator never calls fal, a vision judge, or a publishing workflow.
