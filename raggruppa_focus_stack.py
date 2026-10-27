#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raggruppa in cartelle separate le foto di una scheda che fanno parte della stessa
serie di focus stacking, leggendo i metadati EXIF (pensato per Canon EOS R5, CR3 + JPG/HEIF).

Come decide che due foto sono nella stessa serie:
  1. sono scattate a breve distanza di tempo (default: al massimo 5 secondi fra una e la successiva,
     usando anche i sottosecondi) e
  2. hanno le stesse impostazioni: fotocamera, obiettivo, lunghezza focale, diaframma, ISO
     (con --strict anche il tempo di posa).

Le serie con meno di 3 foto (--min) restano dove sono. File con lo stesso nome (IMG_1234.CR3,
IMG_1234.JPG, IMG_1234.xmp...) viaggiano insieme.

Uso tipico:
    python raggruppa_focus_stack.py  D:\\DCIM\\100EOSR5
    python raggruppa_focus_stack.py  /Volumes/EOS_DIGITAL/DCIM -r --dest ~/Foto/Stack --copy

Prima di toccare qualunque file mostra l'anteprima e chiede conferma.
Per leggere i CR3 serve ExifTool (https://exiftool.org): va bene anche solo il file
exiftool(.exe) messo accanto a questo script. Per JPG/TIFF/HEIC funziona anche senza, con Pillow.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

PHOTO_EXT = [".cr3", ".cr2", ".dng", ".arw", ".nef", ".raf", ".orf", ".rw2",
             ".hif", ".heic", ".heif", ".tif", ".tiff", ".jpg", ".jpeg"]   # in ordine di preferenza per leggere i dati
STACK_PREFIX = "Stack_"
TAGS = ["DateTimeOriginal", "SubSecTimeOriginal", "CreateDate", "ExposureTime", "FNumber", "ISO",
        "FocalLength", "Model", "LensModel", "LensID", "Lens"]


# ----------------------------------------------------------------------------- lettura metadati

def find_exiftool():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("exiftool.exe", "exiftool"):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            return p
    return shutil.which("exiftool")


def read_with_exiftool(exe, paths):
    out = {}
    for i in range(0, len(paths), 50):
        batch = paths[i:i + 50]
        cmd = [exe, "-json", "-n", "-charset", "filename=UTF8"] + ["-" + t for t in TAGS] + batch
        res = subprocess.run(cmd, capture_output=True)
        try:
            rows = json.loads(res.stdout.decode("utf-8", "replace") or "[]")
        except ValueError:
            rows = []
        by_name = {os.path.normpath(r.get("SourceFile", "")): r for r in rows}
        for j, p in enumerate(batch):
            row = by_name.get(os.path.normpath(p))
            if row is None and len(rows) == len(batch):
                row = rows[j]
            if row:
                out[p] = row
    return out


def read_with_pillow(path):
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            sub = ex.get_ifd(0x8769)
    except Exception:
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    iso = sub.get(0x8827)
    if isinstance(iso, (tuple, list)) and iso:
        iso = iso[0]
    return {
        "DateTimeOriginal": sub.get(0x9003) or ex.get(0x0132),
        "SubSecTimeOriginal": sub.get(0x9291),
        "ExposureTime": num(sub.get(0x829A)),
        "FNumber": num(sub.get(0x829D)),
        "ISO": iso,
        "FocalLength": num(sub.get(0x920A)),
        "Model": ex.get(0x0110),
        "LensModel": sub.get(0xA434),
    }


# ----------------------------------------------------------------------------- scansione e raggruppamento

def scan(root, recursive):
    shots = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if recursive:
            dirnames[:] = [d for d in dirnames if not d.startswith(STACK_PREFIX) and not d.startswith(".")]
        else:
            dirnames[:] = []
        for fn in filenames:
            if fn.startswith("."):          # file "._xxx" creati da macOS sulle schede
                continue
            stem = os.path.splitext(fn)[0].lower()
            shots.setdefault((dirpath, stem), []).append(os.path.join(dirpath, fn))
    result = []
    for (_, stem), files in sorted(shots.items()):
        exts = {os.path.splitext(f)[1].lower(): f for f in files}
        primary = next((exts[e] for e in PHOTO_EXT if e in exts), None)
        if primary:
            result.append({"name": os.path.basename(primary), "primary": primary, "files": sorted(files)})
    return result


def parse_time(meta):
    s = str(meta.get("DateTimeOriginal") or meta.get("CreateDate") or "").strip()
    if len(s) < 19:
        return None
    try:
        t = dt.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    sub = str(meta.get("SubSecTimeOriginal", "")).strip()
    if sub.isdigit():
        t += dt.timedelta(seconds=float("0." + sub))
    return t


def rnd(v, n):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def signature(meta, strict):
    lens = meta.get("LensModel") or meta.get("LensID") or meta.get("Lens")
    sig = (meta.get("Model"), str(lens) if lens is not None else None,
           rnd(meta.get("FocalLength"), 1), rnd(meta.get("FNumber"), 1), rnd(meta.get("ISO"), 0))
    if strict:
        sig += (rnd(meta.get("ExposureTime"), 6),)
    return sig


def load_shots(root, recursive, strict, exe):
    shots = scan(root, recursive)
    if not shots:
        return [], 0, 0
    metas = {}
    if exe:
        metas = read_with_exiftool(exe, [s["primary"] for s in shots])
    no_time = 0
    unreadable = 0
    ok = []
    for s in shots:
        meta = metas.get(s["primary"])
        if meta is None and not exe:
            meta = read_with_pillow(s["primary"])
        if not meta:
            unreadable += 1
            continue
        t = parse_time(meta)
        if t is None:
            no_time += 1
            t = dt.datetime.fromtimestamp(os.path.getmtime(s["primary"]))
        s["time"] = t
        s["sig"] = signature(meta, strict)
        ok.append(s)
    return ok, unreadable, no_time


def build_groups(shots, gap, min_size):
    shots = sorted(shots, key=lambda s: (s["time"], s["name"]))
    runs, cur = [], []
    for s in shots:
        if cur:
            d = (s["time"] - cur[-1]["time"]).total_seconds()
            if d > gap:
                runs.append((cur, "pausa di %.1f s" % d, d))
                cur = []
            elif s["sig"] != cur[-1]["sig"]:
                runs.append((cur, "impostazioni diverse", d))
                cur = []
        cur.append(s)
    if cur:
        runs.append((cur, "fine", None))

    groups, singles = [], []
    prev_end_gap = None
    for idx, (run, why_end, _) in enumerate(runs):
        times = [s["time"] for s in run]
        internal = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        info = {
            "shots": run, "start": times[0], "end": times[-1],
            "duration": (times[-1] - times[0]).total_seconds(),
            "max_gap": max(internal) if internal else 0.0,
            "before": prev_end_gap, "why_end": why_end,
        }
        # distanza dalla serie precedente = intervallo registrato al taglio precedente
        if idx > 0:
            info["before"] = (run[0]["time"] - runs[idx - 1][0][-1]["time"]).total_seconds()
        if len(run) >= min_size:
            groups.append(info)
        else:
            singles.extend(run)
    return groups, singles


# ----------------------------------------------------------------------------- spostamento

def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists("%s_%d%s" % (base, n, ext)):
        n += 1
    return "%s_%d%s" % (base, n, ext)


def transfer(src, dst, copy):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    dst = unique_path(dst)            # non sovrascrive mai niente
    if not copy:
        try:
            os.rename(src, dst)       # stesso disco: istantaneo
            return dst
        except OSError:
            pass                      # dischi diversi: si copia e poi si cancella
    shutil.copy2(src, dst)
    if os.path.getsize(src) != os.path.getsize(dst):
        os.remove(dst)
        raise IOError("copia incompleta di " + src)
    if not copy:
        os.remove(src)
    return dst


def folder_name(i, g):
    return "%s%03d_%s_%dfoto" % (STACK_PREFIX, i, g["start"].strftime("%Y%m%d_%H%M%S"), len(g["shots"]))


def apply_groups(groups, dest_root, copy):
    log = {"created": dt.datetime.now().isoformat(timespec="seconds"), "mode": "copy" if copy else "move", "items": []}
    for i, g in enumerate(groups, 1):
        folder = os.path.join(dest_root, folder_name(i, g))
        for s in g["shots"]:
            for f in s["files"]:
                final = transfer(f, os.path.join(folder, os.path.basename(f)), copy)
                log["items"].append({"from": f, "to": final})
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(dest_root, "raggruppamento_log_%s.json" % stamp)
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    return log_path, len(log["items"])


def undo(log_path):
    with open(log_path, encoding="utf-8") as fh:
        log = json.load(fh)
    if log.get("mode") != "move":
        print("Questo log riguarda una copia: per annullare basta cancellare le cartelle Stack_ create.")
        return 1
    back, skipped, folders = 0, 0, set()
    for it in log["items"]:
        if os.path.exists(it["to"]) and not os.path.exists(it["from"]):
            os.makedirs(os.path.dirname(it["from"]), exist_ok=True)
            transfer(it["to"], it["from"], False)
            folders.add(os.path.dirname(it["to"]))
            back += 1
        else:
            skipped += 1
    for d in folders:
        try:
            os.rmdir(d)               # solo se vuota
        except OSError:
            pass
    print("Annullato: %d file riportati al loro posto, %d saltati." % (back, skipped))
    return 0


# ----------------------------------------------------------------------------- interfaccia

def fmt_sec(x):
    return "—" if x is None else ("%.1f s" % x if x < 120 else "%d min %02d s" % (x // 60, x % 60))


def print_preview(groups, singles, total, gap, min_size):
    n_in = sum(len(g["shots"]) for g in groups)
    print("\nFoto analizzate: %d  |  serie trovate (almeno %d scatti, max %.1f s fra uno scatto e l'altro): %d  |  foto raggruppate: %d  |  lasciate dove sono: %d\n"
          % (total, min_size, gap, len(groups), n_in, len(singles)))
    if groups:
        print("  N.  Inizio               Scatti  Durata     Pausa max  Distanza dalla serie prima  Primo file")
        for i, g in enumerate(groups, 1):
            print("  %-3d %s  %-6d  %-9s  %-9s  %-26s  %s" % (
                i, g["start"].strftime("%Y-%m-%d %H:%M:%S"), len(g["shots"]), fmt_sec(g["duration"]),
                fmt_sec(g["max_gap"]), fmt_sec(g["before"]), g["shots"][0]["name"]))
    if singles:
        names = ", ".join(s["name"] for s in sorted(singles, key=lambda s: s["time"])[:6])
        print("\n  Non raggruppate (serie troppo corte): %s%s" % (names, " …" if len(singles) > 6 else ""))
    print()


def main():
    interactive_start = len(sys.argv) == 1
    ap = argparse.ArgumentParser(description="Raggruppa in cartelle le serie di focus stacking leggendo l'EXIF.")
    ap.add_argument("cartella", nargs="?", help="cartella con le foto (es. DCIM/100EOSR5)")
    ap.add_argument("--dest", help="dove creare le cartelle Stack_* (default: dentro la cartella di partenza)")
    ap.add_argument("--gap", type=float, default=5.0, help="secondi massimi fra due scatti della stessa serie (default 5)")
    ap.add_argument("--min", type=int, default=3, dest="min_size", help="scatti minimi per formare una serie (default 3)")
    ap.add_argument("--strict", action="store_true", help="richiede anche lo stesso tempo di posa")
    ap.add_argument("-r", "--recursive", action="store_true", help="include le sottocartelle (es. 100EOSR5, 101EOSR5…)")
    ap.add_argument("--copy", action="store_true", help="copia invece di spostare")
    ap.add_argument("--dry-run", action="store_true", help="mostra solo l'anteprima")
    ap.add_argument("-y", "--yes", action="store_true", help="non chiedere conferma")
    ap.add_argument("--undo", metavar="LOG", help="annulla uno spostamento usando il file raggruppamento_log_*.json")
    args = ap.parse_args()

    if args.undo:
        return undo(args.undo)

    root = args.cartella
    if not root:
        root = input("Trascina qui la cartella con le foto (o scrivi il percorso) e premi Invio: ").strip().strip('"').strip("'")
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        print("Cartella non trovata:", root)
        return 2
    dest = os.path.abspath(os.path.expanduser(args.dest)) if args.dest else root

    exe = find_exiftool()
    if not exe:
        print("ATTENZIONE: ExifTool non trovato. Senza, leggo solo JPG/TIFF/HEIC e i file CR3 vengono saltati.\n"
              "Installalo da https://exiftool.org (oppure metti exiftool.exe accanto a questo script).\n")

    print("Leggo i metadati in", root, "…")
    shots, unreadable, no_time = load_shots(root, args.recursive, args.strict, exe)
    if unreadable:
        print("  %d foto illeggibili (formato non supportato senza ExifTool?): ignorate." % unreadable)
    if no_time:
        print("  %d foto senza orario EXIF: uso la data del file, poco affidabile." % no_time)
    if not shots:
        print("Nessuna foto utilizzabile.")
        return 1

    groups, singles = build_groups(shots, args.gap, args.min_size)
    print_preview(groups, singles, len(shots), args.gap, args.min_size)
    if not groups:
        print("Nessuna serie trovata. Prova ad alzare --gap o ad abbassare --min.")
        return 0
    if args.dry_run:
        return 0

    verb = "copio" if args.copy else "sposto"
    if not args.yes:
        if not sys.stdin.isatty():
            print("Aggiungi --yes per procedere senza conferma.")
            return 1
        if input("Procedo? %s i file in cartelle Stack_* dentro %s [s/N] " % (verb, dest)).strip().lower() not in ("s", "si", "sì", "y", "yes"):
            print("Annullato, non ho toccato nulla.")
            return 0

    log_path, n = apply_groups(groups, dest, args.copy)
    print("Fatto: %d file %s in %d cartelle.\nPer annullare: python %s --undo \"%s\"" % (
        n, "copiati" if args.copy else "spostati", len(groups), os.path.basename(sys.argv[0]), log_path))
    if interactive_start and os.name == "nt":
        input("Premi Invio per chiudere…")
    return 0


if __name__ == "__main__":
    sys.exit(main())