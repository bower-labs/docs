# Bower Help Center — Documentation project instructions

## About this project

- This is the public-facing help center for [Bower](https://bowerlabs.ai), built on [Mintlify](https://mintlify.com)
- Pages are MDX files with YAML frontmatter
- Configuration lives in `docs.json`
- Run `mint dev` to preview locally (auto-selects an available port if 3000 is in use)
- Run `mint broken-links` to check links
- Hosted at `docs.bowerlabs.ai`
- This repo is **public** — treat every file as publicly visible. Never commit API keys, internal URLs, secrets, or system architecture details.
- Run `python3 scripts/validate-docs.py` before opening a PR — it is what CI runs

## Brand and assets

The 2026-08 identity is shared with the marketing site (`bowerlabs.ai`) and the product (`app.bowerlabs.ai`). Each property hosts its own copy of the artwork rather than hotlinking the others, so the files here must stay byte-identical with theirs. `scripts/validate-docs.py` pins the hashes and fails on drift.

- **Colors.** `colors.primary` is Twilight 700 `#3F5C94`, not the core brand blue `#5C88DA`. Mintlify paints `primary` onto inline links and small labels, and `#5C88DA` is 3.02:1 on Parchment — large display text and non-text UI only. The app repo's `packages/frontend/src/theme/colors.brand.ts` carries the full ramps and the reasoning.
- **`logo` and `colors` use the same slot names for opposite things.** `logo.light` is the file rendered in *light* mode, so it holds the dark-ink lockup. `colors.light` is the primary rendered in *dark* mode, so it holds a light step. Mintlify's published schema describes `logo.light` the other way round and the implementation disagrees with it — check a running `mint dev` in both modes, not the schema. Getting it wrong is invisible in review, because whichever mode you happen to be in still renders something.
- **Share cards.** Mintlify generates one per page from the logo, `colors.primary`, and the page's `title` and `description` frontmatter, over `images/og-background.png`. That background is generated — run `python3 scripts/generate-og-background.py`, do not edit the PNG. A page with no `description` gets a card with no subtitle, so keep frontmatter descriptions filled in.
- **Fonts are deliberately not synced.** The siblings self-host GT Ultra and Suisse Int'l; those faces are licensed and this repo is public, so the help center stays on Mintlify's default stack.

## Voice, terminology and the never list

These live in `.mintlify/ASSISTANT.md`, because the help center's AI assistant reads that
file when it answers readers. Read it before writing; it is the one copy.

## Style preferences

- **Spelling is American.** organize, optimize, analyze, summarize, center,
  behavior, color, license, catalog, program. House style went American on
  2026-08-09; the word list lives in the Notion tone-of-voice doc and is
  extracted to `scripts/voice-rules.json`, mirrored in `bower-labs/bower` and
  `bower-labs/website` so all three surfaces read as one dialect. Refreshing
  Notion means refreshing all three. `python3 scripts/check-house-spelling.py`
  enforces it and runs in CI; `--fix` rewrites, and you should read the diff.
  Note `analyse` -> `analyze` (it ends `-yse`, not `-ise`) and that the
  participles drop the `e`: organis**ing** -> organiz**ing**.
- **URL paths are not prose.** `/organisation/...` stays as it is. Renaming a
  directory is a URL migration that needs `redirects` entries in `docs.json`,
  which the Trust Center rename is the worked example of — not a spelling fix.
  The guard excludes link targets and `href`s for this reason.
- **A heading rename changes its anchor, and a redirect `source` cannot carry
  a fragment** (browsers never send it). A `destination` can:
  `/organisation/protocols#protocol-runs` works. Before renaming a heading, grep
  the app repo for `#that-anchor`; `validate-docs.py` checks these docs' own
  links and redirect destinations, but not links from the app.
- **Headings that are linked to use plain characters only**: letters, digits,
  spaces, hyphens and `?.,:()/`. Mintlify keeps apostrophes (as `’`), quotes,
  `&` and dashes in the anchor, so "What's on a run record?" becomes
  `#what’s-on-a-run-record` and every hand-typed link to it breaks. Write "What
  is on a run record?" instead. CI enforces this for linked headings.
- Use active voice and second person ("you")
- Keep sentences concise — one idea per sentence
- Use sentence case for headings
- Bold for UI elements: Click **Settings**
- Code formatting for file names, commands, paths, and code references
- No marketing language. State what the feature does, not how exciting it is.

## Concise, with one source of truth

Our pages tend to run long, and a fact written twice drifts the first time
someone updates only one copy. So:

- **Every fact has one owning page.** The page about a feature owns how it
  works. Every other page that needs it says one sentence and links there
  (`[Undoing the last step](/ai-and-search/live-agent-mode#undoing-the-last-step)`),
  never a paraphrase of the steps, limits, labels or numbers.
- **Numbers, limits and labels live in one place**: a timeout, a retention
  period, a list of supported devices. A second page links instead of
  restating them, because they are what changes.
- **Before writing, grep** for the feature's name and its UI labels across the
  repo. Fold what you find into the owning page or turn it into a link.
- **Say it once on the page too.** No intro that previews the sections, no
  closing summary, no "as mentioned above". A table or a list replaces a
  paragraph that walks through cases.
- **Cut to what a reader does or sees.** Implementation detail, edge cases
  nobody hits and reassurance go. If a section reads well without a sentence,
  delete it.
- **Changelog entries** may summarize the feature page they link to, in a few
  bullets; they are the one exception, and they are frozen once published.
- **Quote labels as rendered**, not from a code template: `Show 10 more (23
  left)` is not `Show 10 more`.

`validate-docs.py` fails when a sentence of 10+ words appears on two pages.
That only catches copy-paste; a reworded repeat is the reviewer's to catch.

## Content boundaries

- Do not document internal admin features, infrastructure, or deployment
- Do not expose API keys, internal URLs, or system architecture details
- Do not document features that are not yet available to users. Docs for a flag-gated feature open as a **draft** PR and merge when the flag widens, or earlier with David's OK
- Do not include screenshots of internal tools or admin panels
