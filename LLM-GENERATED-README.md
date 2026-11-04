# Slide Studio

Local application for creating and editing bilingual Quarto/Reveal.js presentations, managing reusable facts and images, running Python maintenance scripts and AI recipes, and using optional OpenRouter AI Edit and AI Chat.

The backend uses Python's standard library, listening on `127.0.0.1`. The frontend uses HTML, CSS and JavaScript, without a frontend build step.

## Requirements

- Python 3.11+ and a modern browser.
- Quarto CLI for rendering presentations to HTML.
- Chromium or Chrome for automated PDF output and slide-image context, when available. The browser's print interface is an alternative for PDF export.
- Poppler (`pdftoppm`) for converting rendered slides into images for AI requests.
- OpenRouter API key for AI features.

There are no third-party Python packages or additional frontend runtime packages.

Run:

```bash
python app.py
```

Specify another workspace with `python app.py --workspace /path/to/workspace`.

## Application branding

Without branding configuration, the application has no header mark or favicon. A root-level `branding.toml` overrides the application name, short header mark, light and dark accent colors, default new-presentation accent, and an optional logo. The logo path, when specified, must reference a PNG, WebP, or SVG file inside `branding/`. When a logo or mark is provided, it also determines the browser favicon. Branding is an optional application-level configuration, separate from the workspace and user settings. Keeping an existing `branding.toml` preserves the configured appearance; removing it uses the stock appearance.

For example:

```toml
name = "Slide Studio"
mark = "ST."
logo = ""
accent_light = "#346b99"
accent_dark = "#317cae"
slide_accent = "#346b99"
```

Branding is loaded at application startup. The `slide_accent` value is used in the stylesheet of each new presentation; existing presentations retain their own stylesheets.

## Workspace

Presentations have `pt-BR.qmd` and `en.qmd` sources with matching slide IDs. Variants control canvas size and hidden slides. Facts use named tables with value, description, and last-verified date. Assets use virtual paths and contain descriptions and inclusion dates. Presentations, variants and slides also have descriptions. Scripts are stored under `workspace/scripts/` with Python source, metadata and parameters. Recipes are stored under `workspace/recipes/` with instructions and metadata.

The application provides presentation previews, a Quarto source editor, fact tables, an asset file explorer, and editors for scripts and recipes. The source editor compares the current text to the saved version: inserted lines have green backgrounds, deleted original lines appear in red without being editable, and replacements show both versions. Editing a source draft supports local Ctrl+Z and Ctrl+Shift+Z Undo/Redo shortcuts. The slide toolbar can exclude hidden slides from navigation without modifying their visibility, while the individual slide visibility button controls which slides are shown in the chosen variant. The slide references button lists facts and assets referenced in either language. Presentation Settings includes duplication, which copies both languages, variants, descriptions and presentation-local files into the working session. Resource references can be copied and inspected for usage by presentation, language and slide. Facts can be moved between tables, and assets can be duplicated or moved between folders. Entire asset folders can be moved by dragging them onto another folder or a breadcrumb; the asset browser scrolls automatically when dragging near its upper or lower edge. Asset images can be enlarged and inspected with zoom and pan. The interface supports light and dark mode, with the interface palette in `static/theme.css` and branding overrides from `branding.toml`.

`{{fact:Table.key}}` and `{{asset:Folder/name}}` are replaced when rendering; the underlying source retains those references. Renaming or merging a fact or asset rewrites references across presentations. Missing references render placeholders.

AI Edit operates on the selected slide/presentation, fact table/all facts, asset folder/all assets or selected script/all scripts or selected recipe/all recipes. Both AI panels receive a workspace index with presentation, variant, slide, script, and recipe names, identifiers, and descriptions. Fact and asset identifiers and metadata can be retrieved on demand, as can complete presentation sources and bilingual rendered slides. Retrieval never expands the selected AI Edit permissions. AI Chat, AI Edit and Recipes can list changed files and request saved-state or previous-state diffs through the read-only `read_workspace_diff` tool; differences are not included automatically in model requests. All AI interactions receive the current interface selection when available. AI Edit can apply provisional changes, inspect the resulting sources or rendered slides, and refine them before committing one undoable change. Rendered slides are transmitted when requested by the model and supported by the chosen model. The AI model and reasoning effort can be chosen separately in each panel.

All edits use an undoable working state. **Save** persists that state into `workspace/`. The Save indicator also monitors connectivity with the local application server; it does not measure internet connectivity. Git commits are not managed by the application. Saved chats and API settings are kept in `config/`, separately from workspace edits.

See [workspace data model](docs/workspace.md), [editing operations](docs/operations.md), and [AI interaction model](docs/ai.md).

## Scripts

Scripts run only when manually started. They execute in a separate process with `SLIDE_STUDIO_WORKSPACE` pointing at a temporary workspace copy and `SLIDE_STUDIO_PARAMETERS` containing JSON parameter values. Successful changes are imported as one undoable operation. A failure or cancellation does not commit changes to the working state.

Scripts are **not sandboxed** and may access the user's files or network. Review scripts before running them. The application does not install script dependencies. The scripting interface proposed in [TODO.md](TODO.md) remains a design intention; scripts currently use ordinary filesystem operations.

## Recipes

Recipes are named, reusable instructions stored in `workspace/recipes/<id>/instructions.md`, with their name and description in `recipe.json`. They are editable in the Recipes tab and through AI Edit, using the same Apply, Undo/Redo and Save workflow as other resources. A recipe is not a Python script.

Running a recipe opens a confirmation dialog explaining that the AI can edit **all presentations and slides, facts, assets, scripts, recipes and other supported application resources**, regardless of the currently selected view. The dialog also chooses the OpenRouter model and reasoning effort for that run. Recipes use the ordinary compact AI workspace index, current interface selection, resource retrieval tools, provisional editing, inspection and cancellation. Instructions are read when the recipe runs, not frozen when it is created. Each successful run contributes one undoable change to the working session; Save is still required to persist it. An unsuccessful or cancelled run does not commit changes.

Recipe AI can modify existing resources using the structured editing operations. It cannot execute scripts, create image pixels, or autonomously retrieve information from the internet. A recipe may ask the model to use existing workspace facts or images, but external facts and photographs must be supplied through available resources.

## Privacy and output

Source compilation is local, although Quarto documents can explicitly reference online content. OpenRouter requests transmit the workspace index, retrieved textual context, and any rendered slide images requested by the model to the external service and model provider. The terminal can display model-provided reasoning and operational diagnostics, potentially including workspace content. The application does not send model requests until the user initiates an AI interaction.

The application may create its own persistent data under `workspace/` and `config/`. Compilation, PDF intermediates and edit-session history are kept in temporary directories. No application-created persistent files are written elsewhere by default.

## Tests and implementation

Run the Python test suite from the application directory:

```bash
python -m unittest discover -s tests
```

JavaScript navigation and source-diff behavior are tested with Node.js using its built-in test runner:

```bash
node --test tests/navigation.test.js tests/source_diff.test.js
```

Node.js is required only for the JavaScript tests; it is not used by the running application. The Python suite skips the Node-based test if Node.js is unavailable.

The Python backend separates workspace persistence and history (`studio/project.py`), shared validation and serialization (`studio/project_shared.py`), and fact/asset management (`studio/project_resources.py`). AI tool definitions and implementations reside under `studio/operations/`. The browser uses `static/navigation.js` for slide navigation and Reveal.js preview events, and `static/source-diff.js` for source comparison and editable-line rendering; the remaining interface scripts implement resource editors and controls.

## License

The application source is licensed under the GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later). The license text is available at https://www.gnu.org/licenses/agpl-3.0.txt. Presentation materials, institutional branding, and user-supplied assets are separate from the application source.
