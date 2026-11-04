from __future__ import annotations

import re
import html
import os
import signal
import time
from threading import Event, RLock, Thread
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from .project import Project, tree_digest, split_qmd, validate_bilingual_sources
from .variants import displayed_slides, canvas_size

FACT_REF = re.compile(r"\{\{fact:([^}.]+)\.([a-z][a-z0-9_-]*)\}\}")
ASSET_REF = re.compile(r"\{\{asset:([^{}\r\n]+)\}\}")
BRIDGE = """<script>
(function () {
  function announce() {
    if (!window.Reveal || !Reveal.isReady()) return;
    const slide = Reveal.getCurrentSlide();
    const indices = Reveal.getIndices();
    window.parent.postMessage({type: 'studio-slide', id: slide?.id || '', index: indices.h, url:location.pathname}, '*');
  }
  async function printDeck() {
    const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
    const deadline = performance.now() + 5000;
    while (!document.querySelector('.pdf-page') && performance.now() < deadline) await frame();
    const sources = new Set(Array.from(document.querySelectorAll('.slide-art image'), image => image.getAttribute('href')).filter(source => source?.startsWith('../../assets/')));
    await Promise.all(Array.from(sources, source => {
      const image = new Image();
      image.src = source;
      return image.decode().catch(() => {});
    }));
    await document.fonts.ready;
    await frame();
    await frame();
    window.print();
  }
  function connect() {
    if (!window.Reveal || !Reveal.isReady()) { setTimeout(connect, 100); return; }
    Reveal.on('slidechanged', announce);
    window.parent.postMessage({type: 'studio-ready', url:location.pathname}, '*');
    window.addEventListener('message', (event) => {
      if (event.source !== window.parent || event.origin !== new URL(document.baseURI).origin) return;
      if (event.data?.type === 'studio-layout') {
        requestAnimationFrame(() => { Reveal.sync(); Reveal.layout(); announce(); });
      } else if (event.data?.type === 'studio-goto' && typeof event.data.id === 'string') {
        const slides = [...document.querySelectorAll('.reveal .slides > section[id]')];
        const index = slides.findIndex(section => section.id === event.data.id);
        if (index >= 0) Reveal.slide(index);
      }
    });
    announce();
    if (new URLSearchParams(location.search).has('autoprint')) {
      printDeck();
    }
  }
  connect();
})();
</script>
"""


class Renderer:
    def __init__(self, project: Project):
        self.project = project
        self.temp = tempfile.TemporaryDirectory(prefix="studio-preview-")
        self.root = Path(self.temp.name)
        self.cache: dict[tuple[str, str, str, str, bool], str] = {}
        self.locations: dict[str, Path] = {}
        self.cache_lock = RLock()
        self.pdf_cache: dict[str, str] = {}
        self.precompute_version = 0
        self.precompute_thread: Thread | None = None
        self.base_url = ''

    def render(self, pid: str, language: str, variant_id: str, include_hidden: bool = False, cancelled: Event | None = None, source_project: Project | None = None) -> str:
        if language not in ("pt-BR", "en"):
            raise ValueError("Invalid language")
        if shutil.which("quarto") is None:
            raise ValueError("Quarto CLI not found. Install Quarto to render the slide preview")
        current_project = source_project or self.project
        with current_project.lock:
            version = tree_digest(current_project.current)
            cache_key = (version, pid, language, variant_id, include_hidden)
            with self.cache_lock:
                if cache_key in self.cache:
                    token = self.cache[cache_key]
                    return f"/preview/{token}/presentations/{pid}/{language}.html"
            token = uuid4().hex
            directory = self.root / token
            directory.mkdir()
            from .project import snapshot_content, copy_content
            if source_project is not None:
                copy_content(current_project.current, directory)
            else:
                snapshot_content(current_project.current, directory)
            entry = directory / "presentations" / pid / (language + ".qmd")
            original = entry.read_text(encoding="utf-8")
            original_pt = (directory / "presentations" / pid / "pt-BR.qmd").read_text(encoding="utf-8")
            configurations = current_project.variants(pid)
            if variant_id not in configurations["variants"]:
                raise ValueError("Variant not found")
            variant = configurations["variants"][variant_id]
            frontmatter, slides = split_qmd(original)
            visible = set([slide["id"] for slide in slides] if include_hidden else displayed_slides([slide["id"] for slide in slides], configurations, variant_id))
            original = frontmatter + "\n\n".join(slide["source"] for slide in slides if slide["id"] in visible) + "\n"
            original = re.sub(r"(?m)^    (?:width|height):[^\n]*\n", "", original)
            original = original.replace("  revealjs:\n", f'  revealjs:\n    width: {variant["width"]}\n    height: {variant["height"]}\n', 1)
            facts = current_project.facts().get("categories", {})
            assets = current_project.assets().get("assets", {})

            def fact_replace(match: re.Match[str]) -> str:
                category, key = match.group(1), match.group(2)
                value = facts.get(category, {}).get(key)
                return str(value["value"]) if value is not None else f"[Missing fact: {category}.{key}]"

            def asset_replace(match: re.Match[str]) -> str:
                alias = match.group(1)
                asset = assets.get(alias)
                reference = asset.get("file", "") if asset else ""
                if reference and (directory / reference).is_file():
                    return "../../" + reference
                placeholder = directory / "assets" / f"_missing_{uuid4().hex[:12]}.svg"
                placeholder.parent.mkdir(parents=True, exist_ok=True)
                placeholder.write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">'
                    '<rect width="960" height="540" fill="#f4f5f6" stroke="#6b7280" stroke-width="8"/>'
                    '<text x="480" y="270" fill="#374151" text-anchor="middle" font-family="sans-serif" font-size="27">'
                    + html.escape(f"Missing asset: {alias}") + '</text></svg>', encoding="utf-8")
                return "../../assets/" + placeholder.name

            compiled = ASSET_REF.sub(asset_replace, FACT_REF.sub(fact_replace, original))
            entry.write_text(compiled, encoding="utf-8")
        command = ["quarto", "render", entry.name, "--to", "revealjs"]
        if cancelled is not None:
            self.run_cancellable(command, entry.parent, cancelled, 90)
        else:
            try:
                result = subprocess.run(command, cwd=entry.parent, capture_output=True, text=True, timeout=90, check=False, env=None)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Quarto rendering timed out") from exc
            if result.returncode:
                explanation = (result.stderr or result.stdout or "Unknown error").strip()
                raise ValueError("Quarto failed:\n" + explanation[-5000:])
        output = entry.with_suffix(".html")
        if not output.is_file():
            raise ValueError("Quarto did not produce the expected HTML output")
        html_source = output.read_text(encoding="utf-8")
        original_source = original_pt
        base_width, base_height = canvas_size(original_source)
        width, height = variant["width"], variant["height"]
        scale = min(width / base_width, height / base_height)
        dx = (width - base_width * scale) / 2
        dy = (height - base_height * scale) / 2
        scaling = (f'<style>.reveal .slides section .migrated-canvas {{ transform: translate({dx:.5f}px,{dy:.5f}px) scale({scale:.7f}) !important; transform-origin:top left !important; }}</style>')
        html_source = html_source.replace("</head>", scaling + "</head>")
        html_source = html_source.replace("</body>", BRIDGE + "\n</body>")
        output.write_text(html_source, encoding="utf-8")
        with self.cache_lock:
            self.cache[cache_key] = token
            self.locations[token] = directory
            if len(self.locations) > 160:
                stale = next(iter(self.locations))
                shutil.rmtree(self.locations.pop(stale), ignore_errors=True)
                self.cache = {key: value for key, value in self.cache.items() if value != stale}
        return f"/preview/{token}/presentations/{pid}/{language}.html"

    def pdf(self, pid: str, language: str, variant_id: str, base_url: str) -> str:
        preview = self.render(pid, language, variant_id, include_hidden=False)
        with self.cache_lock:
            known = self.pdf_cache.get(preview)
            if known:
                return known
        browser = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable") if shutil.which(name)), None)
        if not browser:
            raise ValueError("Chromium or Chrome is required for PDF generation")
        token = preview.split("/")[2]
        with self.cache_lock:
            directory = self.locations[token]
        output_pdf = directory / "presentations" / pid / (language + "-export.pdf")
        with tempfile.TemporaryDirectory(prefix="studio-pdf-profile-") as profile:
            command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-domain-reliability", "--disable-extensions", "--disable-sync", "--disable-default-apps", "--no-pdf-header-footer", f"--user-data-dir={profile}", "--virtual-time-budget=12000", "--window-size=1280,720", f"--print-to-pdf={output_pdf}", base_url + preview + "?print-pdf"]
            self.run_cancellable(command, directory, Event(), 120)
        if not output_pdf.is_file() or output_pdf.stat().st_size < 100:
            raise ValueError("Chromium did not generate the expected PDF")
        url = f"/preview/{token}/presentations/{pid}/{output_pdf.name}"
        with self.cache_lock:
            self.pdf_cache[preview] = url
        return url

    def schedule_precompute(self, base_url: str) -> None:
        if not shutil.which("quarto"):
            return
        with self.cache_lock:
            self.base_url = base_url
            self.precompute_version += 1
            if self.precompute_thread is not None and self.precompute_thread.is_alive():
                return
            self.precompute_thread = Thread(target=self._precompute, daemon=True, name="studio-render-cache")
            self.precompute_thread.start()

    def _precompute(self) -> None:
        import logging
        log = logging.getLogger(__name__)
        while True:
            with self.cache_lock:
                version = self.precompute_version
            time.sleep(0.7)
            with self.cache_lock:
                if version != self.precompute_version:
                    continue
            with self.project.lock:
                presentations = [(item["id"], list(self.project.variants(item["id"])["variants"])) for item in self.project.presentations()]
            for pid, variants in presentations:
                for variant in variants:
                    for language in ("pt-BR", "en"):
                        with self.cache_lock:
                            if version != self.precompute_version:
                                break
                        try:
                            self.render(pid, language, variant, include_hidden=True)
                            if any(shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")):
                                self.pdf(pid, language, variant, self.base_url)
                        except Exception as exc:
                            log.warning("Presentation rendering: %s (%s, %s): %s", pid, variant, language, exc)
                    else:
                        continue
                    break
                else:
                    continue
                break
            with self.cache_lock:
                if version == self.precompute_version:
                    self.precompute_thread = None
                    return

    def resolve(self, token: str, relative: str) -> Path:
        if token not in self.locations:
            raise ValueError("Preview expired")
        root = self.locations[token].resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("File not found")
        return path

    @staticmethod
    def run_cancellable(command: list[str], cwd: Path, cancelled: Event, timeout: float) -> None:
        from .openrouter import EditCancelled
        if cancelled.is_set():
            raise EditCancelled("Edit cancelled")
        with tempfile.TemporaryFile() as error_log:
            process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=error_log, start_new_session=(os.name == "posix"))
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if cancelled.is_set():
                        raise EditCancelled("Edit cancelled")
                    if time.monotonic() > deadline:
                        raise ValueError("Slide image generation timed out")
                    time.sleep(0.12)
                if process.returncode:
                    error_log.seek(0)
                    stderr = error_log.read().decode("utf-8", errors="replace")
                    raise ValueError("Slide image generation failed: " + stderr[-1500:])
            finally:
                if process.poll() is None:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait()

    def slide_images(self, pid: str, variant_id: str, scope: str, slide_id: str, base_url: str, cancelled: Event, source_project: Project | None = None) -> list[tuple[str, str, bytes]]:
        from .openrouter import EditCancelled
        browser = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable") if shutil.which(name)), None)
        if not browser:
            raise ValueError("Visual context requires Chromium or Google Chrome installed locally")
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise ValueError("Visual context requires pdftoppm (Poppler utilities)")
        current_project = source_project or self.project
        slides = current_project.state(pid)["allSlides"]
        visible = slides
        selected = visible if scope == "presentation" else [slide_id]
        collection: list[tuple[str, str, bytes]] = []
        for language in ("pt-BR", "en"):
            if cancelled.is_set():
                raise EditCancelled("Edit cancelled")
            preview_url = self.render(pid, language, variant_id, include_hidden=True, cancelled=cancelled, source_project=current_project)
            with tempfile.TemporaryDirectory(prefix="studio-images-") as temp:
                root = Path(temp)
                output_pdf = root / "slides.pdf"
                profile = root / "chromium-profile"
                command = [
                    browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                    "--disable-background-networking", "--disable-component-update", "--disable-domain-reliability",
                    "--disable-extensions", "--disable-sync", "--disable-default-apps", "--no-pdf-header-footer",
                    f"--user-data-dir={profile}", "--virtual-time-budget=12000", "--window-size=1280,720",
                    f"--print-to-pdf={output_pdf}", base_url + preview_url + "?print-pdf",
                ]
                self.run_cancellable(command, root, cancelled, 45)
                if not output_pdf.is_file() or output_pdf.stat().st_size < 100:
                    raise ValueError("Chromium did not generate a slide PDF")
                for index, current_slide in enumerate(visible, start=1):
                    if current_slide not in selected:
                        continue
                    if cancelled.is_set():
                        raise EditCancelled("Edit cancelled")
                    prefix = root / f"slide-{index}"
                    self.run_cancellable([
                        pdftoppm, "-f", str(index), "-l", str(index), "-singlefile", "-jpeg",
                        "-jpegopt", "quality=80", "-scale-to", "1280", str(output_pdf), str(prefix),
                    ], root, cancelled, 30)
                    jpg = prefix.with_suffix(".jpg")
                    if not jpg.is_file():
                        raise ValueError(f"PDF doesn't contain the expected page {index} ({language})")
                    collection.append((language, current_slide, jpg.read_bytes()))
        return collection
