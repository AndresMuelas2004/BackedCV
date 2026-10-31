# Decision log

What I decided, what I rejected and why.

## Product

- **I build a CV vs job posting checker**, framed as "is this job worth applying to?" rather than "beat the ATS robot". Most ATS do not auto-reject on keywords; what does reject automatically is knockout questions (work authorization, licenses, minimum years, location).
- **Name: BackedCV.** The `.com` was unregistered and I found no product, package or trademark with that name. I rejected Proofline (domain, PyPI name and a near-identical repository already taken), FitReceipt and WorthApplying.
- **The posting is pasted as text.** I rejected fetching job URLs: job boards' terms and fragile scraping.
- **No accounts and no signup** for the first analysis.

## Scoring and verdict

- **Two scores instead of one opaque match rate:** *Fit* (do I meet the requirements, by meaning) and *Keyword coverage* (would an exact-term search find me). Optimizing the CV can raise coverage, never Fit.
- **The score is computed in code from published weights**, never by the model, so every point can be explained and tested.
- **Knockouts are verdict blockers, not points.** Screening questions are yes/no; mixing them into a percentage hides them.
- **A knockout is only "missing" when the user says so or the CV says so explicitly.** I never guess eligibility from location or names.
- **Every knockout question can be answered yes or no.** Some knockout types (degree, clearance, availability) had no way to be resolved, so the verdict could stay "answer the questions first" forever. A per-requirement answer fixes that; CV evidence still wins over an answer.
- **For ordinary requirements, "unknown" becomes "missing".** In the first real run the model answered "unknown" for skills the CV never mentions. The CV is the only evidence a recruiter sees, so silence means missing. Knockouts are the exception: they stay "unknown" until the user answers the question.
- **The technology-age rule (R2) uses a short list** of 20 technologies whose release years I checked on official sources. I rejected a long list I could not verify one by one.
- **R2 can flag a requirement that R1 already flags.** "5+ years of LangGraph" in a junior role is both too senior for the level and older than the technology; showing both reasons is more useful than hiding one.
- **Compound requirements are split** ("PostgreSQL and Snowflake" becomes two), so one matching word cannot inflate keyword coverage.
- **A broader category counts as partial evidence, never as missing.** "Agent frameworks" in a CV is real evidence for LangChain, but not proof of it, so it scores partial.
- **Every verdict explains itself:** the Fit against the band's threshold and the top missing required items, in whole numbers that match the screen.
- **Only legal bans rule you out on their own.** A missing work permit, security clearance or professional license gives "Likely screened out". A missing language or degree caps the verdict at "Long shot" and goes to the top of the list, because many employers are flexible there. Location and availability become yes/no questions. Answering "No" to any of them still rules you out. Old experience against a posting's window (Kubernetes that ended in 2017 against "within the last 5 years") also caps the verdict at "Long shot" and leads the list, instead of screening the candidate out.

## No invented experience

- **The model cites CV line IDs; code fills in the quotes.** This removes invented quotes.
- **General evidence never becomes a specific tool** (a direction rule), and inferred matches count as partial at most.
- **Every suggested edit goes through deterministic guards and an independent verifier.** Unsupported edits cannot be accepted; edited suggestions are verified again.
- **No generated bullets for missing skills.** That is exactly where these tools invent experience.
- **I measured the no-invention promise and fixed what the measurement found.** On 40 synthetic cases the verifier sometimes let through a rewrite that attached the total years of experience to one role. A language model is not reliable at that arithmetic, so I added a deterministic guard: a computed total can only be used as a total. The verifier is not deterministic, so I keep every run's report.

## Hidden screening barriers and recency

- **Recency is computed in code from the CV's own dates.** Each line inherits the dates of the job it belongs to, so I know when a skill was last used: recent (up to 3 years), aging (3 to 6), stale (over 6). A model never guesses a date.
- **Old evidence loses credit only when the posting states a window** ("within the last 5 years"), always quoted word for word from the posting. Without a stated window, old evidence is a warning and costs no points. A 2017 job is real experience, unless the employer says it is too old.
- **Hidden barriers come from a separate model call that reads the whole posting**, because buried disqualifiers often sit outside the requirement list, in a closing note or a perks paragraph. A barrier whose quote is not found in the posting is dropped. The most common one (no visa sponsorship, right to work in a country) is also found by code patterns, so it never depends on the model alone.
- **Code, not the model, sets the risk level**, by checking each barrier against the CV and the candidate's answers: "you must already have the right to work in the United States" with a CV located in Spain is high risk; a yes answer resolves it and a no confirms it. I rejected asking the model for a rejection probability: three levels with a reason are honest, a percentage would be false precision.
- **Two medium risks combine into one high "composite" risk.** A language level and three office days a week abroad are each tolerable; together they make a silent rejection likely.
- **A risk tied to a knockout keeps its real level.** The extraction can also turn a buried sponsorship sentence into a knockout requirement; capping such risks at medium hid a CV in Spain against "the right to work in the United States". Only the question and the verdict defer to the knockout; the level comes from the CV.
- **"Looks met, but..."** marks a requirement whose keyword is in the CV but whose evidence is too old or blocked. That is exactly where a keyword score misleads.
- **Every edit goes through a three-pass corroboration gate**, each pass a node of the graph: backed by a real CV line (the guards and the verifier), recent enough for the posting's window, and not blocked by a hidden barrier. An edit that fails the second or third pass gets the status "refused: not viable", with the reason, and cannot be accepted.
- **Not-viable requirements are refused before any edit is generated**, so the model is never asked to make old experience look current. The refusal is still listed with its reason: a silent omission would look like a missed opportunity.
- **A CV edit can never fix an eligibility barrier**, so edits aimed at one are refused and the candidate answers the yes/no question instead. An unanswered high risk counts as one more question before the verdict; a no acts like a failed knockout. A barrier that the posting already lists as a knockout requirement is not asked twice.

## The report

- **The report goes from simple to complex.** Early users found the full report overwhelming and too long, and asked for the posting's sentence next to the CV line and deal-breakers kept apart from preferences. So the verdict in one sentence and one number sits at the top, the open yes/no questions right under it, "Improve my CV" locked until they are answered, then a numbered list of what to fix, most damaging first. Three tiers with text labels, not just colours: could rule you out, serious gap, worth improving. Each item shows the posting's sentence next to the CV line and one thing to do. What already works comes after, then how the dates were read, and everything else (all requirements, keyword coverage, the score breakdown, the CV as parsed) is folded into details. Nothing was deleted: it moved down.
- **Short texts everywhere.** Every explanation the app writes is one plain sentence of about 20 words, without internal IDs.
- **Dates are shown, never guessed.** The report lists each job's dates as read and the time counted. A missing month says "month unknown" and counts as the shortest period it allows, so the total says "at least".
- **The landing page shows the result first.** A short example of the report plays before anyone uploads anything, because "paste, upload, press the button" says nothing about what you get.
- **Same CV and same posting give the same verdict and score.** Testing found that a blank line in the posting could move the score from 55 to 72; the text is normalized before every model call. The same testing also fixed a missing "2+ years" counted as a small partial, a question asked twice, a 2023 degree marked "aging", a date glued to a city ("SpainApr 2026") read as January, and suggestions that only stuffed posting words into a line.

## Architecture

- **One LangGraph graph per analysis** with two human-in-the-loop pauses (before optimizing, and the review of suggestions) and parallel fan-out for matching and verification.
- **Files are read in the API, before the graph**, so no file bytes end up in checkpoints.
- **Code applies the accepted changes; a small tool-calling agent only orders the final CV**, with a deterministic fallback. I rejected an agent that writes free text.
- **When the ordering agent is unavailable, the new CV uses a standard section order.** Keeping the original order would put a two-column CV's sidebar (education, skills) before the summary.
- **No RAG, vector database or embeddings for now:** one CV and one posting fit in the model's context. Embeddings come in only if meaning-based matching through the model proves unreliable.
- **The posting review runs beside the matching, not before it.** The R4 review needs the extracted requirements but not the matching, so it runs in parallel and adds no waiting time.
- **I read PDFs as logical lines, not physical ones.** A real run on a two-column CV showed wrapped bullets turning into fragments, and a rewrite of the first fragment left the rest behind as a duplicate bullet. Bullets and paragraphs are now rebuilt before anything else sees them; short list items stay separate.
- **Identical model calls are replayed from a local cache.** Re-running the sample gives the same numbers at no cost.
- **Runs live on the server, not in the browser tab.** Closing or reloading the tab mid-analysis used to leave it stuck. Each step now runs as a server task; a reload picks it up again and a failed step can be retried.
- **Contracts first:** I defined the suggestion and document models before writing the guards, the document assembly and the renderers, so those pieces share one contract.

## Privacy and limits

- **The model never sees contact details.** Email addresses, phone numbers and links are replaced with placeholders before every model call; the app keeps the original text for the report and the new CV. Matching does not need them, and a CV is personal data.
- **Production traces hide inputs and outputs**, so real CVs never reach a third-party trace store. Only synthetic data lives in this repository.
- **Per-IP and daily caps on model-using requests.**
- **A public feedback form in the repository** (a GitHub issue form) asks people not to paste a real CV.

## Model: Claude Haiku 5.5

- **Every model call runs on Claude Haiku 5.5 (Anthropic API).** It started on OpenAI models. For prompts of up to 100K tokens Haiku 5.5 costs the same as the cheap OpenAI model it replaced: $0.10 per million input tokens and $0.50 per million output tokens.
- **One model for both tiers.** The fast and the strong tier both default to `claude-haiku-5-5`, and a setting can still move rewrites and their checks to a bigger model. I kept the strong tier on Haiku too: Claude Sonnet 5.5 costs twenty times as much, and Haiku 5.5 blocked every invented rewrite in the evals.
- **Every prompt stays under 100K tokens.** Past that, a Haiku 5.5 call costs five times as much. The input limits already keep each call at about a quarter of it (a maximal CV and posting came to about 24,000 tokens), so I kept them. The cost shown for each call uses the right rate card, and a longer prompt is logged as a warning.
- **I kept LangChain and LangGraph** with `langchain-anthropic`, so the graph, the order agent and the LangSmith traces stay the same. I rejected rewriting the calls on the bare Anthropic SDK: more code for the same requests.
- **Structured outputs everywhere.** Claude's structured outputs hold each answer to the draft schemas, and its effort level sets how much the model reasons. No temperature: Haiku 5.5 rejects sampling parameters. A request the model declines is not retried, because the same input would be declined again.
- **Effort levels chosen by measurement.** With the verifier at `medium`, the fabrication set blocked 3 of 20 faithful rewrites by mistake; at `high`, 2 of 20 in two runs, still blocking all 20 invented ones. Suggestions at `medium` gave 3 or 4 verified rewrites per run of the demo sample, against 2 or 3 at `low`, for about a tenth more. So `suggest` runs at `medium`, `verify` at `high` and the rest at `low`.

## Stack

- **Backend:** Python 3.12, FastAPI with server-sent events, LangGraph and LangChain, the Anthropic API, LangSmith.
- **Frontend:** React with TypeScript, built with Vite to static files served by FastAPI, with plain CSS. I rejected HTMX (clumsy for highlights, diffs and live scores), Streamlit (looks like a demo), and Tailwind and component libraries (fewer dependencies for a handful of components).
- **Reading CVs:** pdfplumber and python-docx. I rejected PyMuPDF because of its AGPL license.
- **Writing CVs:** python-docx for DOCX and Typst for PDF. I rejected WeasyPrint (system packages in Docker).
- **Tooling:** uv, ruff, pytest, SQLite checkpoints. **License:** MIT.
- **Measurement:** a small fabrication set (suggestions with invented facts, to count how many get blocked) and four end-to-end CV and posting pairs. I rejected a formal eval suite.
- **Deployment:** a public demo on Render's free plan, from a Blueprint in the repository, with Render's GitHub access limited to this repository. Docker Compose runs it locally.
