# Bower Help Center — Documentation project instructions

## About this project

- This is the public-facing help center for [Bower](https://bowerlabs.ai), built on [Mintlify](https://mintlify.com)
- Pages are MDX files with YAML frontmatter
- Configuration lives in `docs.json`
- Run `mint dev` to preview locally (auto-selects an available port if 3000 is in use)
- Run `mint broken-links` to check links
- Hosted at `docs.bowerlabs.ai`
- This repo is **public** — treat every file as publicly visible. Never commit API keys, internal URLs, secrets, or system architecture details.

## About Bower

Bower is an AI-powered research platform that helps scientists capture, organise, and retrieve their lab work without interrupting their experiments. Named for the bowerbird's instinct to collect and organise, Bower does the same for research insights.

## Voice and tone

We sound like a **supportive postdoc.** Not a marketing department. Not a chatbot. A real person who has spent years in labs, who knows the pain of lost data and illegible notebook entries, and who genuinely wants to help you work better.

This person is warm but no-nonsense. They ask smart questions. They pay attention to detail. They remember what you told them last week.

### The five traits

1. **Curious** — We ask clarifying questions, not because we're uncertain, but because precision matters in science and we respect that. We'd rather ask than assume.

2. **Precise** — We get the units right. We use correct terminology. We don't round up, hand-wave, or make vague claims. When we say something works, we explain how. When we're not sure, we say so.

3. **Helpful** — We don't wait to be asked. If we notice something useful, we surface it. But we never take action without permission, and we never interfere with capture. Capture is sacred.

4. **Reliable** — We never overpromise. We always show our working. We acknowledge our limitations. If Bower can't do something yet, we say that plainly.

5. **Warm** — We are collegial, not corporate. We use contractions. We can be dry. We are never sarcastic, never condescending, and never artificially enthusiastic.

### Docs-specific register

For product docs and help center content, the tone is: **precise, step-by-step, technical where needed, still warm, never robotic.**

Example: "Voice capture uses scientific speech recognition trained on domain vocabulary. Accuracy improves as Bower learns your terminology."

### The acid test

Would a postdoc actually say this to a colleague in the lab? If not, rewrite it.

## Terminology

Use these terms — our users are scientists and will notice if we get them wrong.

| Say this | Not this | Why |
|----------|----------|-----|
| **Protocol** | ~~Process / workflow~~ | Researchers use "protocol" for a specific documented procedure |
| **Method** | ~~Technique / approach~~ | A published, high-level scientific technique (e.g., LA-ICP-MS) |
| **Parameters** | ~~Settings / fields~~ | The measurable values within a protocol |
| **Reagents** | ~~Chemicals / substances~~ | What researchers actually say |
| **Specimens / samples** | ~~Items / things~~ | Be specific about what you're referencing |
| **Lab notebook** | ~~Notes / journal~~ | The term of art; "notes" is acceptable only for Bower's own note objects |
| **Transcribe** | ~~Convert / type up~~ | Precise about what the AI does |
| **Extract (values)** | ~~Pull out / grab~~ | The correct term for deriving structured data |
| **Flag / surface** | ~~Alert / notify~~ | What a colleague does, not what an alarm does |
| **Capture** | ~~Record / log / enter~~ | Bower's core verb — speed and minimal friction |
| **Workspace** | ~~Project / account~~ | The data container; "project" means something else |
| **Note** | (use as-is) | Editable text content in Bower |
| **Attachment** | (use as-is) | Original source file |
| **Bird** | (always capitalised) | The AI assistant |
| **Collection** | ~~Folder / group~~ | How notes are grouped |
| **Page tree** | ~~Sidebar / nav~~ | The left-hand navigation panel |
| **Member** | ~~User~~ | A person in a workspace |

### Methods vs. protocols

A **method** is a high-level scientific technique, typically extractable from published papers. A **protocol** is a detailed, operational, step-by-step guide that a specific lab uses to perform that method. Never conflate them.

### Units and precision

Always use correct SI units with proper formatting. Write "°C" not "degrees." Write "µmol/L" not "micromoles per litre" in technical contexts. If you reference a specific number (like ~98% OCR accuracy), make sure it's current and defensible. Don't round up.

## The never list

These are hard rules, not guidelines.

1. **Never overpromise.** Don't claim Bower does something it doesn't do yet. If a feature is in development, say "we're building" or "coming soon."

2. **Never hand-wave.** Don't use phrases like "powerful AI," "cutting-edge technology," or "seamless integration" without explaining what the AI actually does.

3. **Never use hype language.** Banned: revolutionise, disrupt, game-changing, unlock the power of, supercharge, leverage (as a verb), synergy, best-in-class, world-class, next-generation, empower, democratise, reimagine, transform (unless describing a literal data transformation).

4. **Never be patronising.** Our users are scientists. They understand complex systems. They don't need exclamation marks to feel excited. They definitely don't need us celebrating basic actions ("Great job capturing that data!").

5. **Never obscure the AI.** When Bower's AI does something, be transparent about what it did and how confident it is. Never present AI output as verified truth. The researcher is always the authority.

6. **Never use emojis.** Not in the docs, not in examples, not anywhere.

## Style preferences

- Use active voice and second person ("you")
- Keep sentences concise — one idea per sentence
- Use sentence case for headings
- Bold for UI elements: Click **Settings**
- Code formatting for file names, commands, paths, and code references
- No marketing language. State what the feature does, not how exciting it is.

## Content boundaries

- Do not document internal admin features, infrastructure, or deployment
- Do not expose API keys, internal URLs, or system architecture details
- Do not document features that are not yet available to users
- Do not include screenshots of internal tools or admin panels
