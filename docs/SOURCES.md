# Primary documentation and data attribution
Checked October 6, 2026. These sources document the interfaces and seed data. They do not establish successful live provider requests from the development runtime.

- FEC, Candidate master file description: https://www.fec.gov/campaign-finance-data/candidate-master-file-description/
- FEC bulk-download pattern: https://www.fec.gov/files/bulk-downloads/2026/cn26.zip (substitute a supported even cycle and two-digit filename year).
- unitedstates/congress-legislators (CC0; officeholders and service histories): https://github.com/unitedstates/congress-legislators
- Media Cloud FAQ (coverage, no article-body release, API quotas): https://www.mediacloud.org/documentation/faqs
- Media Cloud source guide (source metadata and headquarters geography): https://www.mediacloud.org/documentation/source-guide
- Media Cloud search guide: https://www.mediacloud.org/documentation/search-api-guide
- Official Media Cloud Python client: https://github.com/mediacloud/api
- States Newsroom national/state network and partner directory: https://statesnewsroom.com/newsrooms/
- AllSides methodology, category/native scales, confidence and licensing: https://www.allsides.com/about/media-bias-rating-methods
- Individual AllSides rating evidence links are recorded in data/source_bias_seed.csv. These are attributed provider judgments, not objective political truth or this project's calibration.
- GDELT DOC API documentation: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- GDELT 2.0 documentation: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- ProQuest U.S. Newsstream archive product: https://about.proquest.com/en/products-services/nationalsnews_shtml/ (check per-title coverage and your license; the importer does not assume access).
- Local NLI baseline model card: https://huggingface.co/MoritzLaurer/deberta-v3-base-zeroshot-v2.0-c
- Colab FAQ and resource limitations: https://research.google.com/colaboratory/faq.html

## License and attribution notes
AllSides states its ratings are available for research/noncommercial reuse with attribution under CC BY-NC 4.0; commercial reuse requires a license agreement. Preserve attribution and do not redistribute the six seed ratings as unrestricted data. Native numerical scores were not fabricated from categories. The ordinal display mapping is a project transformation.

States Newsroom directory metadata provide a discovery seed only. Partnership does not necessarily mean common ownership. Do not redistribute underlying articles merely because their URLs are public. Each source's full-text permission is separate.

No copyrighted full articles, raw historical archive texts, API credentials, or model weights are bundled. Synthetic test texts are explicitly labeled. Dependency/model licenses apply separately.
