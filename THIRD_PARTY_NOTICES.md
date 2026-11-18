# Third-party components

* **plotly.js** (basic bundle) 2.35.2, `fludash/vendor/plotly-basic-2.35.2.min.js`, is
  Copyright 2012-2024 Plotly, Inc., MIT license (https://github.com/plotly/plotly.js/blob/master/LICENSE).
  It is inlined into every dashboard HTML file this project builds.
* **`fludash/locations.csv`** is copied from `auxiliary-data/locations.csv` in the CDC FluSight
  forecast hub (https://github.com/cdcepi/FluSight-forecast-hub).

The surveillance data the pipeline downloads belongs to its publishers (CDC, Delphi/CMU, Kinsa).
None of it is stored in this repository. Kinsa data is licensed and must not be published.
