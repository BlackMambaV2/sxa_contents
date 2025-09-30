import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, Iterable

from PIL import Image, UnidentifiedImageError

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".svg"}
CACHE_FILENAME = ".picons-cache.json"


def sha1_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_cache(cache_path: Path) -> Dict[str, Any]:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache_path: Path, data: Dict[str, Any]) -> None:
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rasterize_svg_with_cairosvg(svg_path: Path, out_png: Path) -> None:
    import cairosvg  # type: ignore
    cairosvg.svg2png(url=str(svg_path), write_to=str(out_png))


def rasterize_svg_with_inkscape(svg_path: Path, out_png: Path) -> None:
    # Inkscape >= 1.0 : -o / --export-filename
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW on Windows
    subprocess.run(
        ["inkscape", str(svg_path), "-o", str(out_png)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def open_image_any(path: Path, svg_engine: str = "auto") -> Optional[Image.Image]:
    """
    Ouvre une image en RGBA.
    - .svg: moteur contrôlé par svg_engine: auto|cairosvg|inkscape|skip
    - autres formats: Pillow
    """
    ext = path.suffix.lower()

    if ext == ".svg":
        tmp_png = path.with_suffix(".tmp._rasterized.png")

        def _load_tmp() -> Optional[Image.Image]:
            img = Image.open(tmp_png).convert("RGBA")
            tmp_png.unlink(missing_ok=True)
            return img

        if svg_engine == "skip":
            print(f"[INFO] SVG ignoré (svg-engine=skip): {path}")
            return None

        if svg_engine in ("auto", "cairosvg"):
            try:
                rasterize_svg_with_cairosvg(path, tmp_png)
                return _load_tmp()
            except Exception as e:
                if svg_engine == "cairosvg":
                    print(f"[ERROR] CairoSVG échec pour {path} → {type(e).__name__}: {e}")
                    return None
                else:
                    print(f"[INFO] CairoSVG indisponible/échec pour {path} → {type(e).__name__}: {e}")

        if svg_engine in ("auto", "inkscape"):
            from shutil import which
            if not which("inkscape"):
                if svg_engine == "inkscape":
                    print(f"[ERROR] Inkscape introuvable dans le PATH (svg-engine=inkscape): {path}")
                else:
                    print(f"[INFO] Inkscape non trouvé dans le PATH, .svg ignoré: {path}")
                return None
            try:
                rasterize_svg_with_inkscape(path, tmp_png)
                return _load_tmp()
            except Exception as e:
                print(f"[ERROR] Inkscape échec pour {path} → {type(e).__name__}: {e}")
                return None

        # Si on arrive ici, rien n'a marché
        return None

    # Formats bitmap classiques
    try:
        return Image.open(path).convert("RGBA")
    except (UnidentifiedImageError, FileNotFoundError) as e:
        print(f"[WARN] Ouverture échouée: {path} ({e})")
        return None


def fit_into_frame(logo: Image.Image, frame_size: Tuple[int, int], allow_upscale: bool = True) -> Image.Image:
    frame_w, frame_h = frame_size
    lw, lh = logo.size

    scale_w = frame_w / lw
    scale_h = frame_h / lh
    scale = min(scale_w, scale_h)
    if not allow_upscale:
        scale = min(scale, 1.0)

    new_w = max(1, int(lw * scale))
    new_h = max(1, int(lh * scale))
    logo_resized = logo.resize((new_w, new_h), Image.LANCZOS)

    frame = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    x = (frame_w - new_w) // 2
    y = (frame_h - new_h) // 2
    frame.paste(logo_resized, (x, y), logo_resized)
    return frame


def process_one(input_path: Path, output_path: Path, frame_size: Tuple[int, int], allow_upscale: bool, svg_engine: str) -> bool:
    img = open_image_any(input_path, svg_engine=svg_engine)
    if img is None:
        return False
    picon = fit_into_frame(img, frame_size, allow_upscale=allow_upscale)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        picon.save(output_path, format="PNG", optimize=True)
        return True
    except Exception as e:
        print(f"[ERROR] Sauvegarde échouée: {output_path} ({e})")
        return False


def top_level_dir_of(rel: Path) -> Optional[str]:
    if len(rel.parts) == 0:
        return None
    return rel.parts[0]


def parse_csv_list(val: Optional[str]) -> set[str]:
    if not val:
        return set()
    return {x.strip() for x in val.split(",") if x.strip()}


def matches_any_pattern(path: Path, patterns: Iterable[str]) -> bool:
    s = str(path).replace("\\", "/")
    for pat in patterns:
        if Path(s).match(pat):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(
        description="Génère des picons 512x250 PNG transparents, avec cache et filtrage par pays/dossier."
    )
    ap.add_argument("input_dir", type=Path, help="Dossier d'entrée (arborescence par pays)")
    ap.add_argument("output_dir", type=Path, help="Dossier de sortie")
    ap.add_argument("--width", type=int, default=512, help="Largeur de la frame (def: 512)")
    ap.add_argument("--height", type=int, default=250, help="Hauteur de la frame (def: 250)")
    ap.add_argument("--prefix", type=str, default="sxa_", help="Préfixe du fichier de sortie (def: sxa_)")
    ap.add_argument("--no-upscale", action="store_true", help="Ne pas agrandir les logos plus petits que la frame")
    ap.add_argument("--mode", choices=["all", "changed", "missing"], default="all",
                    help="all = tout refaire, changed = seulement ce qui a changé, missing = seulement ce qui manque")
    ap.add_argument("--only", type=str, default=None,
                    help='Limiter à certains pays/dossiers de 1er niveau (ex: "Portugal,France")')
    ap.add_argument("--exclude", type=str, default=None,
                    help='Exclure certains pays/dossiers de 1er niveau (ex: "Archives,Test")')
    ap.add_argument("--match", type=str, default=None,
                    help='Filtrer par motif glob relatif (ex: "Portugal/*.png" ou "*.svg")')
    ap.add_argument("--clean", action="store_true", help="Vider le dossier de sortie avant génération")
    ap.add_argument("--dry-run", action="store_true", help="Afficher les actions sans écrire sur le disque")
    ap.add_argument("--svg-engine", choices=["auto", "cairosvg", "inkscape", "skip"], default="auto",
                    help="Moteur pour les .svg (def: auto)")

    args = ap.parse_args()

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir
    frame_size = (args.width, args.height)
    prefix: str = args.prefix
    allow_upscale = not args.no_upscale
    mode: str = args.mode
    only_set = parse_csv_list(args.only)
    exclude_set = parse_csv_list(args.exclude)
    match_patterns = parse_csv_list(args.match)
    svg_engine: str = args.svg_engine

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] Dossier d'entrée introuvable: {input_dir}")
        raise SystemExit(1)

    if args.clean and output_dir.exists():
        print(f"[CLEAN] Suppression de {output_dir}")
        if not args.dry_run:
            shutil.rmtree(output_dir, ignore_errors=True)

    cache_path = output_dir / CACHE_FILENAME
    cache = load_cache(cache_path)

    cfg_fingerprint = {
        "frame_w": frame_size[0],
        "frame_h": frame_size[1],
        "prefix": prefix,
        "allow_upscale": allow_upscale,
        "svg_engine": svg_engine,
        "version": 2,
    }
    cache_cfg = cache.get("_config")
    if cache_cfg != cfg_fingerprint and mode != "all":
        print("[INFO] Les paramètres ont changé depuis la dernière exécution → forçage 'changed' sur tout.")
        mode = "changed"

    total, ok, skipped = 0, 0, 0
    to_process: list[tuple[Path, Path, Path]] = []

    for path in input_dir.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(input_dir)
        ext = path.suffix.lower()

        top = top_level_dir_of(rel)
        if top is None:
            if only_set and (not match_patterns):
                continue
        else:
            if only_set and top not in only_set:
                continue
            if exclude_set and top in exclude_set:
                continue

        if match_patterns and not matches_any_pattern(rel, match_patterns):
            continue

        if ext not in IMAGE_EXTS:
            continue

        out_rel = rel.with_suffix(".png")
        out_rel = out_rel.parent / (prefix + out_rel.name)
        out_path = output_dir / out_rel

        to_process.append((path, rel, out_path))

    files_cache: Dict[str, Any] = cache.get("files", {})

    for abs_in, rel_in, abs_out in to_process:
        total += 1
        key = str(rel_in).replace("\\", "/")

        do_build = False
        reason = "all"

        if mode == "all":
            do_build = True
        else:
            src_hash = sha1_of_file(abs_in)
            entry = files_cache.get(key)
            if entry is None:
                reason = "new"
                do_build = True
            else:
                if entry.get("cfg") != cfg_fingerprint:
                    reason = "config-changed"
                    do_build = True
                elif mode == "missing" and not abs_out.exists():
                    reason = "missing-out"
                    do_build = True
                elif mode == "changed" and entry.get("src_sha1") != src_hash:
                    reason = "content-changed"
                    do_build = True

            if not do_build and not abs_out.exists() and mode != "changed":
                reason = "missing-out"
                do_build = True

        if do_build:
            print(f"[BUILD:{reason}] {rel_in} -> {abs_out.relative_to(output_dir)}")
            if not args.dry_run:
                ok_flag = process_one(abs_in, abs_out, frame_size, allow_upscale, svg_engine)
                if ok_flag:
                    ok += 1
                    files_cache[key] = {"src_sha1": sha1_of_file(abs_in), "cfg": cfg_fingerprint}
                else:
                    skipped += 1
        else:
            print(f"[SKIP] {rel_in}")
            skipped += 1

    if not args.dry_run:
        cache["_config"] = cfg_fingerprint
        cache["files"] = files_cache
        output_dir.mkdir(parents=True, exist_ok=True)
        save_cache(cache_path, cache)

    print("\n=== RÉSUMÉ ===")
    print(f"Éligibles: {total}")
    print(f"Générés:   {ok}")
    print(f"Passés:    {skipped}")
    print(f"Mode:      {mode}")
    print(f"Sortie:    {output_dir.resolve()}")
    if args.only:
        print(f"Only:      {args.only}")
    if args.exclude:
        print(f"Exclude:   {args.exclude}")
    if args.match:
        print(f"Match:     {args.match}")
    print(f"SVG engine: {svg_engine}")


if __name__ == "__main__":
    main()
