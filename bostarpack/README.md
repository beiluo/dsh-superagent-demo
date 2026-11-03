# Bostar Pack — static export site

English-only marketing site for **Qingdao Bostar Packing Machinery Co., Ltd.**

- **Live site:** https://beiluo.github.io/dsh-superagent-demo/bostarpack/
- **Runtime:** pure static files. No build step, no backend, no database, no external CDN, no cookies or analytics.
- **Preview:** open `index.html` in a browser, or serve the repository root with any static file server.

## Pages

| Page | Purpose |
| --- | --- |
| `index.html` | Home — positioning, industries, featured machines, factory capability, service |
| `products.html` | Full machine catalogue with industry filters and line equipment |
| `machines/*.html` | 16 machine detail pages with features, spec tables and applications |
| `solutions.html` | Packaging solutions by industry, plus pack examples |
| `about.html` | Company, production base, values and export markets |
| `service.html` | Installation, training, warranty, spare parts and FAQ |
| `contact.html` | Contact details and a static inquiry form |

## Structure

```text
bostarpack/
  index.html
  products.html
  solutions.html
  about.html
  service.html
  contact.html
  machines/                 # one page per machine
  assets/
    css/site.css            # single hand-written stylesheet
    js/site.js              # navigation, filter, reveal, mailto form
    img/machines/           # product photos
    img/specs/              # model and dimension tables
    img/manufacturing.jpg   # in-house manufacturing band
    img/og-cover.jpg        # 1200×630 social card
    img/favicon.svg
  sitemap.xml
  robots.txt
```

## Editing

The HTML is committed as the source of truth. There is no runtime template engine.

- Shared header, footer, buttons and section blocks live in each page. When changing navigation or footer links, update the same block on every page.
- All asset and page links are **relative**, so the site works at a domain root or under a sub-path such as `/dsh-superagent-demo/bostarpack/`.
- Machine pages share a common layout: breadcrumb, media, facts, feature grid, specification table, applications, related machines, CTA.
- Product filters use `data-industry` on each card; add a token to both the card and the filter bar to extend a category.

## Content and images

Product names, model numbers, dimension tables and machine photos come from the company's existing site, `https://www.bostarpack.com.cn/`. The English marketing copy, layout and visual system were written for this export edition.

Specification tables are images from the company's catalogue. They are shown as-is, with a note that final parameters are confirmed in the contract.

## Deployment

The repository's GitHub Pages source is the **`main` branch, repository root**. This site is published from the `bostarpack/` directory, so the public URL is:

```text
https://<owner>.github.io/<repository>/bostarpack/
```

To deploy elsewhere, copy the `bostarpack/` directory to any static host. If a custom domain is attached later, update:

- `<link rel="canonical">`, `og:url` and `og:image` in each page's `<head>`
- `sitemap.xml` and `robots.txt`
- the JSON-LD `Organization` block in `index.html`

## Local service note

This deliverable is static only. It does not start a server and does not bind, proxy or restart any local port. The local service on port 8010 is out of scope and was not touched.

## Visual evidence

Before/after captures used for review are in `docs/evidence/`:

- `home-before.jpg` — source site `bostarpack.com.cn`, Chinese template, 1440 px wide
- `home-after.jpg` — this site, 1440 px wide
- `products-before.jpg` — source product listing, 1440 px wide
- `products-after.jpg` — this site's catalogue, 1440 px wide
- `machine-after.jpg` — BOSW detail page, 1440 px wide
- `mobile-after.jpg` — home page at 390 px wide

Captured on 2026-11-03 with headless Firefox. The source site's client-side product carousel did not render in the headless capture, so the product listing page is used for the catalogue comparison.
