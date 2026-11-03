# Visual evidence — Bostar Pack export site

Captured on **2026-11-03** with headless Firefox (Playwright 1.x, Firefox 148) on Linux, at a 1440 × 900 viewport (full-page captures) and 390 × 844 for mobile.

| File | Revision | Page |
| --- | --- | --- |
| `home-before.jpg` | Source site `https://www.bostarpack.com.cn/` | Chinese home page |
| `home-after.jpg` | This site, `/bostarpack/` | English home page |
| `products-before.jpg` | Source site `https://www.bostarpack.com.cn/?products_13/` | Chinese product listing |
| `products-after.jpg` | This site, `/bostarpack/products.html` | English machine catalogue |
| `machine-before.jpg` | Source site `https://www.bostarpack.com.cn/?products_39/170.html` | Chinese BOSW detail page |
| `machine-after.jpg` | This site, `/bostarpack/machines/bosw.html` | BOSW detail page |
| `mobile-after.jpg` | This site, `/bostarpack/` | Mobile home, 390 px |
| `mobile-menu-after.jpg` | This site, `/bostarpack/` | Mobile navigation open |

The source site is a Chinese CMS template. Its client-side product carousel did not render in the headless capture, so `products-before.jpg` (a fully rendered product listing) is used for the catalogue comparison.

The "after" captures come from the exact static files in this directory, served under the same sub-path used by GitHub Pages (`/dsh-superagent-demo/bostarpack/`).
