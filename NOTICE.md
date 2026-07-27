# Third-Party Components

This integration depends on the following open-source libraries. They are
**installed at runtime by Home Assistant** (declared in
`custom_components/epcube_multi/manifest.json`) and are **not redistributed**
in this repository. Their license terms govern their own distribution, not this
project's source tree.

| Component | License | Project |
|-----------|---------|---------|
| NumPy | BSD 3-Clause | https://numpy.org |
| SciPy | BSD 3-Clause | https://scipy.org |
| Pillow | MIT-CMU (HPND) | https://python-pillow.org |
| PyCryptodome | BSD 2-Clause / Public Domain | https://www.pycryptodome.org |

## Solver provenance

The captcha solver in `custom_components/epcube_multi/auth.py` is original work
by the project author, ported from the author's own EPCubeGraph project. As of
v1.2.0 it uses **SciPy / NumPy / Pillow** (via their public APIs) for the
image template-match, replacing an earlier OpenCV implementation — the swap was
made because Home Assistant's container runs on musllinux, for which
`opencv-python-headless` publishes no wheel. The module contains no third-party
source code; it calls the libraries above through their published interfaces.

This project itself is licensed under the MIT License — see [`LICENSE`](LICENSE).
