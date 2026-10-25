# Connector capability matrix

| Action | WordPress (companion plugin) | Shopify (Admin GraphQL) | GitHub (App → PR) | Public site |
|---|---|---|---|---|
| Meta description | ✅ direct · rollback ✅ | ✅ products, collections (seo), pages (`global.description_tag`) · rollback ✅ | ✅ pull request · rollback = close/revert PR | recommendation |
| SEO title | ✅ direct · rollback ✅ | ✅ · rollback ✅ | ✅ pull request | recommendation |
| Internal links | recommendation (review-first) | recommendation | recommendation | recommendation |
| Structured data | recommendation (review-first) | recommendation | recommendation | recommendation |
| Canonical / robots / redirects | restricted (manual) | restricted | restricted | — |
| Theme / template edits | — | review-only, never automated | — | — |
| Concurrency control | plugin `expected_version` (409 on conflict) | `updatedAt` re-read before write | blob `sha` on update | — |
| Verification | REST re-read + live HTML | Admin API re-read + live HTML | PR merged + live HTML (awaiting deploy until then) | — |
| Ownership verification | plugin token | primary domain match | repo homepage match, or meta/DNS/file | meta tag / DNS TXT / file |
| Permissions | Application Password for a user with the plugin's *Lodestar SEO Agent* role | `read/write_products`, `read/write_content` | contents R/W, pull requests R/W, metadata R (selected repo) | none |
| Status in this repo | implemented; tested against fixture; real site requires credentials | implemented; tested against API fake; real store requires credentials | implemented; tested against API fake; real repo requires a GitHub App | implemented |

SEO plugins: Yoast and Rank Math fields are writable through the companion plugin; with no SEO
plugin the companion plugin stores and outputs the tags itself. All in One SEO stores data in
custom tables and is **read-only** in V1. Yoast caches values in its indexables table, so live
verification may stay "pending" until the page is re-indexed by Yoast — verification will never
report success unless the live HTML shows the value.
