# Workspace data model

The workspace holds editable presentations and shared resources. The application creates a temporary working copy for editing; Save writes the current working copy into `workspace/`. Undo/redo act on the temporary state, not Git.

## Presentations

`presentations/<id>/presentation.json` contains `name` (string, 1–100 characters) and `description` (string, at most 2,000 characters). The folder name is the stable internal identifier. Duplicating a presentation creates a new folder with a new identifier and copies its contents; shared facts and assets remain shared. The `pt-BR.qmd` and `en.qmd` files contain Quarto YAML preambles followed by slides with headings of the form `## Title {#slide-id}`. Corresponding slides must use the same identifiers in the same order.

`presentations/<id>/slides.json` stores `{"descriptions":{"slide-id":"..."}}`. Slide descriptions are shared between languages and independent of slide headings and contents. The application uses heading order as the slide order. The preview can omit hidden slides from navigation without changing variant visibility. Fact and asset references in the currently selected slide can be inspected in both languages.

`presentations/<id>/variants.json` stores `default` and `variants`. Each variant has `name`, `description`, integer `width`, integer `height`, and `hidden_slides` (slide identifier list). Some migrated presentations also contain a `migration` object describing their origins. Slide visibility is independent of language. A presentation must retain at least one visible slide.

A `.qmd` file may refer to a stylesheet in the workspace. Scripts and arbitrary executable Quarto code are not part of the presentation authoring model; sources use Reveal.js with `execute: enabled: false`.

## Facts

`facts.json` has a `categories` dictionary mapping table names to dictionaries of fact keys. Each fact has `value` (string), `description` (string), and `updated` (ISO date or null). The template reference `{{fact:Table.key}}` is replaced at render time. Renaming, merging, or moving facts between tables updates existing slide references. Deleting a referenced fact leaves an unresolved placeholder visible on its slides.

## Assets

`assets.json` has `assets`, keyed by each asset's full virtual path, and `folders`, a list of virtual folder paths. An asset has `file` (path relative to workspace), `description`, `category`, `added`, and `updated`. Asset paths may have nested folders or exist directly in the root. `{{asset:Folder/subfolder/name}}` and `{{asset:name}}` reference assets in `.qmd` source. Moving, renaming and merging assets update existing references. Moving a folder relocates all its descendants and updates their source references. Duplicating an asset copies its image bytes to an independent file and registers a separate alias; subsequent edits to either copy do not affect the other. Virtual folder paths do not require physical directory moves.

File size and intrinsic dimensions are read from the image files when needed, not stored as durable metadata. Raster dimensions are in pixels. SVG `viewBox` dimensions can be shown when explicit pixel dimensions are unavailable.

## Scripts

`scripts/<id>/main.py` is the Python source. `scripts/<id>/script.json` stores `name`, `description`, and `parameters`. Each parameter has `name`, `label`, `type` (`text`, `number`, or `boolean`), `default`, and `required`.

Scripts are run manually as subprocesses against a temporary workspace copy. `SLIDE_STUDIO_WORKSPACE` provides the temporary directory and `SLIDE_STUDIO_PARAMETERS` holds a JSON object. Scripts are not sandboxed and have the host user's filesystem and network permissions. The application imports successful changes as one undoable operation.

## Recipes

`recipes/<id>/instructions.md` contains user-authored AI instructions (up to 2,000,000 characters), and `recipes/<id>/recipe.json` contains `name` (1–100 characters) and `description` (up to 2,000 characters). Each folder name is a stable lowercase identifier.

Recipe creation, editing and deletion participate in ordinary session Undo/Redo and Save. Running a recipe invokes AI editing against all supported resources, with the workspace index and current interface selection as context. A single successful run commits one undoable operation. Running a recipe does not execute its instructions as a local program.

## Application configuration

Application-level branding is configured by optional root-level `branding.toml`, independently of workspace content and user settings. New presentations receive the configured default slide accent. Existing presentation stylesheets retain their original colors.


User preferences, OpenRouter API keys, and saved chats reside in `config/`, outside the presentation workspace. They are not included in workspace Save or undo/redo. Chat messages are stored in `config/chats.json`; the API key in `config/settings.json` is written with restrictive permissions.
