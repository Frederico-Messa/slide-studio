# AI interaction model

## Editing

AI Edit accepts a natural-language instruction and returns structured `{"edits":[...]}` operations. The application validates the response against the active editing scope and applies the complete transaction atomically. Changes participate in undo/redo and are written to the workspace only when saved.

| View | Narrow scope | Broad scope |
| --- | --- | --- |
| Slides / Source | Current slide in both languages | Entire presentation and configuration |
| Facts | Current table | All facts |
| Assets | Current folder recursively | All assets |
| Scripts | Current script | All scripts |
| Recipes | Current recipe | All recipes |

Every request includes a compact workspace index, the requested editing target, and the current interface selection. The model can retrieve source files, metadata, styles, workspace diffs, and rendered slides on demand. Retrieval never expands the permitted editing scope. Source and rendered slide retrieval always provide both Portuguese and English.

The model returns targeted operations rather than complete replacement source files. It can apply provisional operations to an isolated editing state, then retrieve sources or rendered slides from that state and submit further operations. A final `{"edits": [...]}` response finishes the request; `{"edits": []}` is valid when provisional edits have already been applied. The entire result is committed to the session as one undoable change. Cancellation, validation failure, or an unsuccessful request discards the provisional state. A successful edit still requires **Save** to persist in the workspace. `studio/operations/catalog.py` defines editing operations; the implementations validate scope and contents. See [operations](operations.md).

## Chat

AI Chat is read-only. Both AI Chat and AI Edit receive a workspace index containing presentation, variant, slide, and script and recipe identifiers, names or titles, and descriptions. Slide titles are included in both languages. Facts and asset identifiers are not included in the initial index; the model can list them through `list_all_facts` and `list_all_assets`, then retrieve metadata using the prefix-aware tools. Detailed variant configurations, full slide source, styles, script source, and recipe instructions are retrieved when requested. The chat has no access to modifying operations or script execution. Each chat request also identifies the presentation, variant, language, and slide currently selected in the interface, if available. This selection does not add source or image content to the request.

## Recipe execution

Recipes store instructions and metadata in the workspace and may be created or edited manually or through AI Edit. A recipe run is initiated by the user in the Recipes tab. Before running it, the dialog explains that the model can modify any presentation and slide and all facts, assets, scripts, recipes and other supported resources. The user chooses the OpenRouter model and reasoning effort for the run.

The recipe text is supplied as the instruction in an ordinary AI editing request, together with the compact workspace index and current UI selection. The model retrieves resources, including saved-state and previous-state diffs, on demand and may apply provisional edits before responding. Presentation and slide operations identify their presentation, so one run can change multiple presentations and resource types. The validated changes are committed together as one Undo/Redo step, or discarded on cancellation or failure. Executing a recipe cannot run Python scripts or access arbitrary filesystem paths through the AI tools.

## Retrieval

Read-only tools are defined in `studio/operations/retrieval.py` and described in [operations](operations.md). The model selects tools, supplies registered resource identifiers (or workspace-relative paths for diff retrieval), and receives the corresponding content. Tool calls are processed in rounds; valid requests do not grant filesystem access outside the specified resource types. A retrieval error is returned as a tool result, allowing the model to correct its request. System instructions ask the model to avoid redundant retrievals and use tools efficiently.

The `read_workspace_diff` tool compares the working state to the last saved workspace (`against="saved"`, the default) or to the previous undo/redo state (`against="previous"`). Without a path it returns only the names of changed files; a relative file or folder path retrieves matching unified diffs. In an editing session, it reads provisional changes without altering the comparison baseline from the original workspace. AI Chat has the same read-only diff tool as AI Edit and Recipes.

Slide-image tools render Quarto/Reveal.js in both languages, convert the resulting PDF pages into JPEG images, and supply those images in a subsequent multimodal message. This requires a vision-capable OpenRouter model, a local Chromium/Chrome executable, and `pdftoppm`. Any hidden slides remain available for retrieval. Assets are represented through textual metadata.

Requests are streamed, and the user can stop generation. AI Edit also exposes `apply_provisional_edits` in addition to the read-only retrieval tools. AI Chat has no editing tools. A tool loop allows up to 48 model rounds and 160 retrieval calls; repeated identical requests are curtailed to prevent loops. Individual retrieval responses are not shortened by character count. Actual provider context and output constraints remain applicable.

## Model settings and privacy

AI Edit and AI Chat each have independent model and reasoning-effort settings. Chats retain their selections. Chat token indicators use provider-reported usage rather than estimates.

Workspace context is transmitted only when the user submits an AI request. OpenRouter and the model provider receive the workspace index, requests, retrieved sources and any rendered slides the model requests. The terminal may display model-provided reasoning.
