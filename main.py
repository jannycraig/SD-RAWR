import os
import re
import shutil
import string
import subprocess
import threading
import sys
import logging
import locale
import traceback
import atexit
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from pyfatfs.PyFat import PyFat
from pyfatfs.PyFatFS import PyFatFS
from fs.errors import InsufficientStorage

APP_NAME = "SD RAWR"
VERSION = "1.0.0"
ALLOWED_MB = [128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]
SPLIT_SIZE = 4000 * 1024 * 1024
COPY_CHUNK = 4 * 1024 * 1024


BG = "#10131c"
PANEL = "#181c28"
PANEL_2 = "#202535"
FG = "#f3f5fb"
MUTED = "#9da7bd"
PURPLE = "#9b35e8"
PURPLE_DARK = "#65209b"
TEAL = "#27d5ce"
TEAL_DARK = "#168f91"
DANGER = "#e05a6a"



def app_directory() -> Path:
    """Directory containing SDRAWR.exe when frozen, otherwise this source file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LOG_PATH = app_directory() / "logs.txt"


def setup_logging():
    logger = logging.getLogger("SDRAWR")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        try:
            handler = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            logger.addHandler(handler)
        except Exception:

            pass

    return logger


LOGGER = setup_logging()

logging.addLevelName(logging.DEBUG, "デバッグ")
logging.addLevelName(logging.INFO, "情報")
logging.addLevelName(logging.WARNING, "警告")
logging.addLevelName(logging.ERROR, "エラー")
logging.addLevelName(logging.CRITICAL, "重大")


def log(message, *args, level=logging.INFO, exc_info=False):
    try:
        LOGGER.log(level, message, *args, exc_info=exc_info)
        for handler in LOGGER.handlers:
            try:
                handler.flush()
            except Exception:
                pass
    except Exception:
        pass


def log_exception(prefix: str, exc: BaseException):
    log("%s: %s: %s", prefix, type(exc).__name__, exc,
        level=logging.ERROR, exc_info=True)


def global_exception_hook(exc_type, exc_value, exc_tb):
    try:
        LOGGER.critical(
            "UNCAUGHT EXCEPTION",
            exc_info=(exc_type, exc_value, exc_tb)
        )
        for handler in LOGGER.handlers:
            handler.flush()
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = global_exception_hook


@atexit.register
def _log_shutdown():
    log("SD RAWR プロセスを終了します。")


def human_size(num_bytes: int) -> str:
    n = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024.0 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024.0


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", name)
    name = name.rstrip(" .")
    return name or "sd"


def folder_stats(folder: Path):
    log("フォルダーをスキャン中: %s", folder)
    total = files = dirs = largest = 0
    for current, dirnames, filenames in os.walk(folder):
        dirs += len(dirnames)
        for filename in filenames:
            p = Path(current) / filename
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += size
            files += 1
            largest = max(largest, size)
    return total, files, dirs, largest


def estimated_required_bytes(total_bytes: int, file_count: int, dir_count: int) -> int:
    metadata = (file_count + dir_count + 64) * 96 * 1024
    percentage = max(32 * 1024 * 1024, int(total_bytes * 0.08))
    return total_bytes + metadata + percentage


def recommended_size_mb(total_bytes: int, file_count: int, dir_count: int):
    need = estimated_required_bytes(total_bytes, file_count, dir_count)
    for mb in ALLOWED_MB:
        if mb * 1024 * 1024 >= need:
            return mb
    return None


def fat_type_for_size(size_mb: int) -> int:
    return PyFat.FAT_TYPE_FAT16 if size_mb <= 2048 else PyFat.FAT_TYPE_FAT32


def make_volume_label(name: str) -> str:
    label = re.sub(r"[^A-Za-z0-9 _-]", "", name.upper()).strip()
    return (label[:11] or "VIRTUALSD")


def ensure_fat_dir(fat: PyFatFS, path: str):
    if not path or path == "/":
        return
    current = ""
    for part in [p for p in path.replace("\\", "/").split("/") if p]:
        current += "/" + part
        if not fat.exists(current):
            fat.makedir(current)


def copy_folder_into_fat(source: Path, image_path: Path, progress_cb=None, stop_cb=None):
    total, _, _, largest = folder_stats(source)
    if largest > 0xFFFFFFFF:
        raise ValueError("The source contains a file larger than FAT32's 4 GiB per-file limit.")

    copied = 0
    fat = PyFatFS(str(image_path), preserve_case=True, utc=False, lazy_load=True)
    try:
        for current, dirnames, filenames in os.walk(source):
            rel_root = Path(current).relative_to(source)
            rel_str = "" if str(rel_root) == "." else rel_root.as_posix()
            ensure_fat_dir(fat, "/" + rel_str if rel_str else "/")

            for dirname in dirnames:
                dest_dir = "/" + (Path(rel_str) / dirname).as_posix() if rel_str else "/" + dirname
                ensure_fat_dir(fat, dest_dir)

            for filename in filenames:
                if stop_cb and stop_cb():
                    raise RuntimeError("Cancelled")

                src = Path(current) / filename
                dest = "/" + (Path(rel_str) / filename).as_posix() if rel_str else "/" + filename
                ensure_fat_dir(fat, str(Path(dest).parent).replace("\\", "/"))

                with src.open("rb") as inp, fat.openbin(dest, "w") as out:
                    while True:
                        block = inp.read(COPY_CHUNK)
                        if not block:
                            break
                        out.write(block)
                        copied += len(block)
                        if progress_cb:
                            progress_cb(copied, max(total, 1), f"Copying {src.name}")
    finally:
        fat.close()


def create_raw_image(source: Path, output_raw: Path, size_mb: int, label: str,
                     progress_cb=None, stop_cb=None):
    log("RAW イメージ作成開始: 元=%s 出力=%s サイズ=%s MiB ラベル=%s", source, output_raw, size_mb, label)
    output_raw = Path(output_raw)
    output_raw.parent.mkdir(parents=True, exist_ok=True)

    if not output_raw.parent.is_dir():
        raise FileNotFoundError(f"Output folder does not exist: {output_raw.parent}")

    size_bytes = size_mb * 1024 * 1024

    if output_raw.exists():
        output_raw.unlink()


    if progress_cb:
        progress_cb(0, 1, f"Allocating {size_mb} MiB image...")
    with output_raw.open("w+b") as f:
        f.truncate(size_bytes)

    if progress_cb:
        progress_cb(0, 1, f"Formatting {size_mb} MiB FAT image...")

    pf = PyFat()
    try:
        pf.mkfs(
            str(output_raw),
            fat_type_for_size(size_mb),
            size=size_bytes,
            sector_size=512,
            number_of_fats=2,
            label=label,
        )
    finally:
        try:
            pf.close()
        except Exception:
            pass

    try:
        copy_folder_into_fat(source, output_raw, progress_cb, stop_cb)
    except Exception:
        output_raw.unlink(missing_ok=True)
        raise


def split_raw(raw_path: Path, split_size=SPLIT_SIZE, progress_cb=None, stop_cb=None):
    log("RAW 分割開始: %s / 1パート=%sバイト", raw_path, split_size)
    total = raw_path.stat().st_size
    done = 0
    parts = []
    with raw_path.open("rb") as src:
        index = 1
        while done < total:
            if stop_cb and stop_cb():
                raise RuntimeError("Cancelled")
            part_path = raw_path.with_name(raw_path.name + f".{index:03d}")
            remaining = min(split_size, total - done)
            with part_path.open("wb") as dst:
                while remaining:
                    block = src.read(min(COPY_CHUNK, remaining))
                    if not block:
                        break
                    dst.write(block)
                    remaining -= len(block)
                    done += len(block)
                    if progress_cb:
                        progress_cb(done, total, f"Splitting part {index:03d}")
            parts.append(part_path)
            index += 1
    return parts


def discover_parts(first_part: Path):
    if not first_part.name.lower().endswith(".001"):
        raise ValueError("Select the .001 file.")
    base = first_part.with_name(first_part.name[:-4])
    parts = []
    i = 1
    while True:
        p = base.with_name(base.name + f".{i:03d}")
        if not p.exists():
            break
        parts.append(p)
        i += 1
    if not parts:
        raise FileNotFoundError("No split parts were found.")
    return base, parts


def combine_parts(first_part: Path, output_raw: Path, progress_cb=None, stop_cb=None):
    log("分割 RAW 結合開始: 先頭=%s 出力=%s", first_part, output_raw)
    _, parts = discover_parts(first_part)
    total = sum(p.stat().st_size for p in parts)
    done = 0
    output_raw.parent.mkdir(parents=True, exist_ok=True)

    with output_raw.open("wb") as dst:
        for index, part in enumerate(parts, 1):
            if stop_cb and stop_cb():
                raise RuntimeError("Cancelled")
            with part.open("rb") as src:
                while True:
                    block = src.read(COPY_CHUNK)
                    if not block:
                        break
                    dst.write(block)
                    done += len(block)
                    if progress_cb:
                        progress_cb(done, total, f"Combining part {index:03d}")
    return output_raw




def find_imdisk():
    """Find imdisk.exe in PATH or common Windows locations."""
    candidates = [
        shutil.which("imdisk"),
        shutil.which("imdisk.exe"),
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "imdisk.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Sysnative" / "imdisk.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def available_drive_letters():
    used = {letter for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")}
    return [
        letter for letter in reversed(string.ascii_uppercase)
        if letter not in used and letter not in ("A", "B")
    ]


def _decode_console_bytes(data: bytes) -> str:
    """
    ImDisk のコンソール出力をデコードする。
    通常の ImDisk 出力は ANSI/OEM/UTF-8 であり、UTF-16 として
    誤判定すると日本語/中国語のような文字化けになるため、
    NUL バイトが多い場合だけ UTF-16 を候補にする。
    """
    if not data:
        return ""

    encodings = []

    nul_ratio = data.count(b"\x00") / max(len(data), 1)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or nul_ratio > 0.20:
        encodings += ["utf-16", "utf-16le", "utf-16be"]

    try:
        encodings.append(locale.getpreferredencoding(False))
    except Exception:
        pass

    encodings += ["mbcs", "utf-8", "cp1252", "cp437", "cp932"]

    seen = set()
    best = None
    best_score = None

    for enc in encodings:
        if not enc or enc.lower() in seen:
            continue
        seen.add(enc.lower())

        try:
            decoded = data.decode(enc, errors="replace")
        except Exception:
            continue

        replacement_penalty = decoded.count("\ufffd") * 1000
        nul_penalty = decoded.count("\x00") * 1000
        nonprintable = sum(
            not (ch.isprintable() or ch in "\r\n\t")
            for ch in decoded
        )
        high_unicode = sum(ord(ch) > 0x2FFF for ch in decoded)

        score = (
            replacement_penalty
            + nul_penalty
            + nonprintable * 50
            + high_unicode * 10
        )

        if best is None or score < best_score:
            best = decoded
            best_score = score

    return best if best is not None else data.decode("utf-8", errors="replace")


def _run_imdisk(args, purpose="コマンド"):
    exe = find_imdisk()
    if not exe:
        raise RuntimeError(
            "ImDisk was not found.\n\n"
            "Install ImDisk Virtual Disk Driver, then restart SD RAWR."
        )

    command = [exe] + list(args)

    log("========== ImDisk %s ==========", purpose)
    log("ImDisk 実行ファイル: %s", exe)
    try:
        st = Path(exe).stat()
        log("ImDisk 実行ファイルサイズ: %s バイト", st.st_size)
        log("ImDisk 実行ファイル更新時刻: %s", st.st_mtime)
    except Exception as exc:
        log_exception("ImDisk 実行ファイル情報の取得に失敗", exc)

    log("作業ディレクトリ: %s", os.getcwd())
    log("コマンド引数: %r", command)
    log("コマンドライン: %s", subprocess.list2cmdline(command))

    result = subprocess.run(
        command,
        capture_output=True,
        text=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )

    stdout = _decode_console_bytes(result.stdout)
    stderr = _decode_console_bytes(result.stderr)

    log("終了コード: %s", result.returncode)
    log("標準出力バイト数: %s", len(result.stdout or b""))
    log("標準エラーバイト数: %s", len(result.stderr or b""))
    log("標準出力（デコード後）:\n%s", stdout if stdout else "<empty>")
    log("標準エラー（デコード後）:\n%s", stderr if stderr else "<empty>")
    log("========== ImDisk %s 終了 ==========", purpose)

    class Result:
        pass

    decoded = Result()
    decoded.returncode = result.returncode
    decoded.stdout = stdout
    decoded.stderr = stderr
    decoded.stdout_bytes = result.stdout
    decoded.stderr_bytes = result.stderr
    return decoded


def probe_imdisk():
    """Log a verbose environment/probe snapshot for troubleshooting."""
    exe = find_imdisk()
    log("========== ImDisk 環境確認開始 ==========")
    log("検出した ImDisk パス: %r", exe)
    log("sys.executable: %s", sys.executable)
    log("sys.frozen: %s", getattr(sys, "frozen", False))
    log("プラットフォーム: %s", sys.platform)
    log("プロセス作業ディレクトリ: %s", os.getcwd())
    log("USERNAME: %s", os.environ.get("USERNAME", ""))
    log("WINDIR: %s", os.environ.get("WINDIR", ""))
    log("PROCESSOR_ARCHITECTURE: %s", os.environ.get("PROCESSOR_ARCHITECTURE", ""))

    if not exe:
        log("ImDisk 確認を中止: 実行ファイルが見つかりません。", level=logging.WARNING)
        return


    try:
        _run_imdisk(["-?"], purpose="ヘルプ/バージョン確認")
    except Exception as exc:
        log_exception("ImDisk ヘルプ/バージョン確認に失敗", exc)

    try:
        _run_imdisk(["-l"], purpose="全体マウント一覧確認")
    except Exception as exc:
        log_exception("ImDisk 全体一覧確認に失敗", exc)

    log("========== ImDisk 環境確認終了 ==========")


def _drive_visible(drive: str) -> bool:
    drive = drive.rstrip(":").upper() + ":"
    return os.path.exists(drive + "\\")


def _normalize_imdisk_image_path(path_text: str) -> str:
    if not path_text:
        return ""

    value = path_text.strip().strip('"')


    if value.startswith("\\??\\"):
        value = value[4:]

    try:
        return os.path.normcase(os.path.abspath(value))
    except Exception:
        return os.path.normcase(value)


def find_existing_mounts_for_image(raw_path: Path):
    target = _normalize_imdisk_image_path(str(raw_path))
    matches = []

    try:
        for mount in list_imdisk_mounts():
            mounted_path = _normalize_imdisk_image_path(mount.get("image", ""))
            if mounted_path and mounted_path == target:
                matches.append(mount)
    except Exception as exc:
        log_exception("同じ RAW の既存マウント確認に失敗", exc)

    return matches


def mount_raw(raw_path: Path, drive_letter: str, read_only=True):
    raw_path = Path(raw_path)
    drive = drive_letter.rstrip(":").upper() + ":"

    log("========== マウント処理開始 ==========")
    log("RAW パス: %s", raw_path)
    log("指定ドライブ: %s", drive)
    log("読み取り専用: %s", read_only)

    if not raw_path.is_file():
        raise FileNotFoundError(f"RAW image does not exist: {raw_path}")

    existing_mounts = find_existing_mounts_for_image(raw_path)
    if existing_mounts:
        mounted_at = []
        for mounted in existing_mounts:
            place = mounted.get("drive") or f"ImDisk unit {mounted.get('unit', '?')}"
            mounted_at.append(f"{place} ({mounted.get('mode', 'unknown mode')})")

        log("同じ RAW が既にマウントされています: %r", existing_mounts, level=logging.WARNING)

        if read_only:
            raise RuntimeError(
                "This RAW image is already mounted by ImDisk:\n\n"
                + "\n".join(mounted_at)
                + "\n\nUse the mounted-drive list to open or unmount the existing copy."
            )

        raise RuntimeError(
            "This RAW image is already mounted by ImDisk:\n\n"
            + "\n".join(mounted_at)
            + "\n\nUnmount the existing copy before mounting it read/write."
        )

    stat = raw_path.stat()
    log("RAW サイズ: %s バイト (%s)", stat.st_size, human_size(stat.st_size))
    log("RAW 更新タイムスタンプ: %s", stat.st_mtime)

    try:
        with raw_path.open("rb") as fh:
            boot = fh.read(512)
        log("読み取ったブートセクタ: %d バイト", len(boot))
        log("ブートシグネチャ [510:512]: %r", boot[510:512] if len(boot) >= 512 else b"")
        log("FAT16 マーカー [54:62]: %r", boot[54:62] if len(boot) >= 62 else b"")
        log("FAT32 マーカー [82:90]: %r", boot[82:90] if len(boot) >= 90 else b"")
        log("先頭64バイト（16進数）: %s", boot[:64].hex(" "))
    except Exception as exc:
        log_exception("RAW ブートセクタ確認に失敗", exc)

    if _drive_visible(drive):
        raise RuntimeError(f"Drive {drive} is already in use.")

    args = ["-a", "-f", str(raw_path), "-m", drive]
    if read_only:
        args += ["-o", "ro"]

    result = _run_imdisk(args, purpose="マウント")

    combined = "\n".join(
        x.strip() for x in (result.stdout, result.stderr) if x and x.strip()
    ).strip()

    if result.returncode != 0:
        log("ドライブが表示される前にマウントに失敗しました。", level=logging.ERROR)
        log("========== マウント処理終了（失敗） ==========")
        raise RuntimeError(
            f"ImDisk failed to mount the RAW image (exit {result.returncode}).\n\n"
            f"{combined or 'No textual error was returned.'}\n\n"
            "See logs.txt for the full verbose ImDisk command/output."
        )

    import time
    for attempt in range(30):
        visible = _drive_visible(drive)
        log("ドライブ表示確認 %d/30 %s: %s", attempt + 1, drive, visible)
        if visible:
            log("マウント成功: %s -> %s", raw_path, drive)
            log("========== マウント処理終了（成功） ==========")
            return drive
        time.sleep(0.1)

    log(
        "ImDisk は成功を返しましたが、3秒後もドライブが表示されません。",
        level=logging.WARNING
    )
    log("========== マウント処理終了（成功応答・表示遅延） ==========")
    return drive


def unmount_raw(drive_letter: str):
    drive = drive_letter.rstrip(":").upper() + ":"
    log("========== アンマウント処理開始 ==========")
    log("ドライブ: %s", drive)
    log("アンマウント前のドライブ表示状態: %s", _drive_visible(drive))

    result = _run_imdisk(["-d", "-m", drive], purpose="アンマウント")

    combined = "\n".join(
        x.strip() for x in (result.stdout, result.stderr) if x and x.strip()
    ).strip()

    if result.returncode != 0:
        log("通常アンマウントに失敗。強制アンマウントを試します。", level=logging.WARNING)
        forced = _run_imdisk(["-D", "-m", drive], purpose="強制アンマウント")
        forced_text = "\n".join(
            x.strip() for x in (forced.stdout, forced.stderr) if x and x.strip()
        ).strip()
        if forced.returncode != 0:
            log("強制アンマウントにも失敗しました。", level=logging.ERROR)
            raise RuntimeError(
                forced_text or combined or "ImDisk failed to unmount the drive."
            )

    import time
    for attempt in range(20):
        visible = _drive_visible(drive)
        log("アンマウント後の表示確認 %d/20 %s: %s", attempt + 1, drive, visible)
        if not visible:
            break
        time.sleep(0.1)

    log("========== アンマウント処理終了 ==========")


def list_imdisk_mounts():
    """
    Parse ImDisk's global `-l` listing, then query each discovered unit.
    Verbose raw output is always written to logs.txt.
    """
    log("========== ImDisk マウント一覧更新開始 ==========")

    exe = find_imdisk()
    if not exe:
        log("ImDisk 実行ファイルが見つかりません。", level=logging.WARNING)
        return []

    global_result = _run_imdisk(["-l"], purpose="全体マウント一覧")
    global_output = (global_result.stdout or "") + "\n" + (global_result.stderr or "")
    log("全体一覧の生テキスト:\n%s", global_output if global_output.strip() else "<empty>")

    units = re.findall(r"\\Device\\ImDisk(\d+)", global_output, flags=re.I)

    if not units:
        units = re.findall(r"(?im)^\s*ImDisk(\d+)\s*$", global_output)

    if not units:
        units = re.findall(r"(?im)^\s*(\d+)\s*$", global_output)

    units = list(dict.fromkeys(units))
    log("解析した ImDisk ユニット番号: %r", units)

    mounts = []

    for unit in units:
        detail = _run_imdisk(["-l", "-u", str(unit)], purpose=f"ユニット {unit} 確認")
        output = (detail.stdout or "") + "\n" + (detail.stderr or "")
        log("ユニット %s の生詳細:\n%s", unit, output if output.strip() else "<empty>")

        drive = ""
        for pattern in (
            r"(?im)^\s*(?:Drive letter|Mount point)\s*:\s*([A-Z]:)",
            r"(?im)^\s*(?:Drive letter|Mount point)\s*=\s*([A-Z]:)",
            r"(?<![A-Za-z0-9])([A-Z]):\\?(?=\s|$)",
        ):
            m = re.search(pattern, output, flags=re.I)
            if m:
                drive = m.group(1).upper()
                if not drive.endswith(":"):
                    drive += ":"
                break

        image = ""
        for pattern in (
            r"(?im)^\s*(?:Image file|Backing file|File name|Image path)\s*:\s*(.+?)\s*$",
            r"(?im)^\s*(?:Image file|Backing file|File name|Image path)\s*=\s*(.+?)\s*$",
        ):
            m = re.search(pattern, output)
            if m:
                image = m.group(1).strip().strip('"')
                break

        if not image:
            m = re.search(
                r'(?:\\\?\?\\)?([A-Za-z]:\\[^\r\n"]+\.(?:raw|img|bin|dd))',
                output,
                flags=re.I
            )
            if m:
                image = m.group(1).strip()

        if image:
            image = image.strip().strip('"')
            if image.startswith("\\??\\"):
                image = image[4:]

        mode = (
            "Read-only"
            if re.search(r"(?i)\bReadOnly\b|\bRead-only\b|\bRead only\b", output)
            else "Read/write"
        )

        parsed = {
            "unit": str(unit),
            "drive": drive,
            "image": image,
            "mode": mode,
        }
        log("ユニット %s の解析結果: %r", unit, parsed)
        mounts.append(parsed)

    log("最終マウント一覧: %r", mounts)
    log("========== ImDisk マウント一覧更新終了 ==========")
    return mounts


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1100x720")
        self.minsize(980, 650)
        self.configure(bg=BG)

        self._style_ui()

        log("SD RAWR %s 起動。実行/ソースディレクトリ: %s", VERSION, app_directory())
        log("ログファイル: %s", LOG_PATH)

        try:
            logo_path = Path(__file__).parent / "assets" / "sdrawr.png"
            if logo_path.exists():
                icon = tk.PhotoImage(file=str(logo_path))
                self.iconphoto(True, icon)
                self._icon_ref = icon
                log("アプリロゴを読み込みました: %s", logo_path)
            else:
                log("アプリロゴが見つかりません: %s", logo_path, level=logging.WARNING)
        except Exception as e:
            log_exception("アプリロゴの読み込みに失敗", e)

        self.source_var = tk.StringVar()
        self.folder_size_var = tk.StringVar(value="No folder selected")
        self.card_name_var = tk.StringVar(value="sd")
        self.card_size_var = tk.StringVar(value="Auto")
        self.split_var = tk.BooleanVar(value=False)
        self.output_dir_var = tk.StringVar(value=str(Path.cwd()))

        self.part_var = tk.StringVar()
        self.parts_info_var = tk.StringVar(value="No split image selected")
        self.join_output_var = tk.StringVar()

        self.mount_raw_var = tk.StringVar()
        self.drive_var = tk.StringVar(value="R:")
        self.read_only_var = tk.BooleanVar(value=True)
        self.mount_status_var = tk.StringVar(value="ImDisk: checking...")
        self.session_mounts = {}

        self.split_existing_var = tk.StringVar()
        self.split_existing_info_var = tk.StringVar(value="No RAW selected")
        self.keep_original_split_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0)
        self.cancel_requested = False
        self.busy = False
        self._last_logged_progress_bucket = -1

        self._build_ui()
        probe_imdisk()
        self._refresh_mount_status()

    def _style_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL_2,
                        bordercolor=PANEL_2, lightcolor=PANEL_2, darkcolor=PANEL_2,
                        font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("Muted.Panel.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 23))
        style.configure("Accent.TLabel", background=BG, foreground=TEAL, font=("Segoe UI Semibold", 10))
        style.configure("TLabelframe", background=PANEL, foreground=TEAL, bordercolor=PURPLE_DARK)
        style.configure("TLabelframe.Label", background=PANEL, foreground=TEAL, font=("Segoe UI Semibold", 11))
        style.configure("TEntry", fieldbackground=PANEL_2, foreground=FG, insertcolor=FG, bordercolor="#343b52")
        style.configure("TCombobox", fieldbackground=PANEL_2, foreground=FG, arrowcolor=TEAL, bordercolor="#343b52")
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", FG)])
        style.configure("TButton", background=PURPLE_DARK, foreground=FG, borderwidth=0, padding=(10, 7))
        style.map("TButton",
                  background=[("active", PURPLE), ("pressed", TEAL_DARK), ("disabled", "#343849")],
                  foreground=[("disabled", "#7e8494")])
        style.configure("Accent.TButton", background=PURPLE, foreground="white", padding=(12, 9))
        style.map("Accent.TButton", background=[("active", "#b24cf1"), ("pressed", PURPLE_DARK)])
        style.configure("Teal.TButton", background=TEAL_DARK, foreground="white")
        style.map("Teal.TButton", background=[("active", TEAL), ("pressed", TEAL_DARK)])
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", FG)])
        style.configure("Horizontal.TProgressbar", troughcolor=PANEL_2, background=TEAL, bordercolor=PANEL_2)

    def _build_ui(self):
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(fill="x")

        logo_path = Path(__file__).parent / "assets" / "sdrawr.png"
        try:
            self.header_logo = tk.PhotoImage(file=str(logo_path))

            x_sub = max(1, round(self.header_logo.width() / 86))
            y_sub = max(1, round(self.header_logo.height() / 74))
            self.header_logo_small = self.header_logo.subsample(x_sub, y_sub)
            tk.Label(
                header,
                image=self.header_logo_small,
                bg=BG,
                borderwidth=0,
                highlightthickness=0
            ).pack(side="left", padx=(0, 14))
        except Exception as e:
            log_exception("ヘッダーロゴの表示に失敗", e)

        titlebox = ttk.Frame(header)
        titlebox.pack(side="left")
        ttk.Label(titlebox, text="SD RAWR", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titlebox, text="Your AIO SD.RAW Manager - by Ｄｉａ！♪～☆",
                  style="Accent.TLabel").pack(anchor="w")

        body = ttk.Frame(self, padding=(16, 8, 16, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Create Virtual SD", padding=14)
        right = ttk.LabelFrame(body, text="Split RAW / Mount", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        left.columnconfigure(1, weight=1)
        right.columnconfigure(1, weight=1)


        ttk.Label(left, text="Source folder", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(left, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=7)
        ttk.Button(left, text="Browse", command=self.choose_source).grid(row=0, column=2)

        ttk.Label(left, text="Folder size", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Label(left, textvariable=self.folder_size_var, style="Muted.Panel.TLabel").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=7)

        ttk.Label(left, text="Virtual SD name", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(left, textvariable=self.card_name_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=7)

        ttk.Label(left, text="Card size", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        sizes = ["Auto"] + [f"{x} MB" for x in ALLOWED_MB]
        ttk.Combobox(left, state="readonly", values=sizes, textvariable=self.card_size_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=7)

        ttk.Label(left, text="Output folder", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(left, textvariable=self.output_dir_var).grid(row=4, column=1, sticky="ew", padx=7)
        ttk.Button(left, text="Browse", command=self.choose_output).grid(row=4, column=2)

        ttk.Checkbutton(left, text="Split final RAW into 4000 MiB parts (.001, .002, ...)",
                        variable=self.split_var).grid(row=5, column=0, columnspan=3, sticky="w", pady=(14, 6))

        ttk.Label(left,
                  text="Copies the selected folder's contents directly to the SD root.\n"
                       "The source folder itself is not added.",
                  style="Muted.Panel.TLabel", justify="left").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(8, 8))

        self.create_btn = ttk.Button(left, text="CREATE SD CARD", style="Accent.TButton", command=self.start_create)
        self.create_btn.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(16, 0))


        ttk.Label(right, text="First split file", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(right, textvariable=self.part_var).grid(row=0, column=1, sticky="ew", padx=7)
        ttk.Button(right, text="Browse", command=self.choose_part).grid(row=0, column=2)

        ttk.Label(right, text="Detected parts", style="Panel.TLabel").grid(row=1, column=0, sticky="nw", pady=5)
        ttk.Label(right, textvariable=self.parts_info_var, style="Muted.Panel.TLabel").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=7)

        ttk.Label(right, text="Output RAW", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(right, textvariable=self.join_output_var).grid(row=2, column=1, sticky="ew", padx=7)
        ttk.Button(right, text="Save as", command=self.choose_join_output).grid(row=2, column=2)

        self.combine_btn = ttk.Button(right, text="COMBINE RAW", command=self.start_combine)
        self.combine_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 12))

        ttk.Label(right, text="Split existing RAW", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 5))
        ttk.Entry(right, textvariable=self.split_existing_var).grid(row=4, column=1, sticky="ew", padx=7)
        ttk.Button(right, text="Browse", command=self.choose_existing_raw).grid(row=4, column=2)

        ttk.Label(right, textvariable=self.split_existing_info_var, style="Muted.Panel.TLabel").grid(
            row=5, column=1, columnspan=2, sticky="w", padx=7)
        ttk.Checkbutton(
            right,
            text="Keep original .raw after splitting",
            variable=self.keep_original_split_var
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 4))

        self.split_existing_btn = ttk.Button(
            right,
            text="SPLIT EXISTING RAW",
            command=self.start_split_existing
        )
        self.split_existing_btn.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(6, 14))

        ttk.Separator(right).grid(row=8, column=0, columnspan=3, sticky="ew", pady=4)


        ttk.Label(right, text="Mount RAW image", style="Panel.TLabel").grid(row=9, column=0, sticky="w", pady=(14, 5))
        ttk.Entry(right, textvariable=self.mount_raw_var).grid(row=9, column=1, sticky="ew", padx=7)
        ttk.Button(right, text="Browse", command=self.choose_mount_raw).grid(row=9, column=2)

        ttk.Label(right, text="Drive letter", style="Panel.TLabel").grid(row=10, column=0, sticky="w", pady=5)
        self.drive_combo = ttk.Combobox(right, state="readonly", textvariable=self.drive_var, width=8)
        self.drive_combo.grid(row=10, column=1, sticky="w", padx=7)

        ttk.Checkbutton(right, text="Read-only mount (recommended)",
                        variable=self.read_only_var).grid(row=11, column=0, columnspan=3, sticky="w", pady=6)

        ttk.Label(right, textvariable=self.mount_status_var, style="Muted.Panel.TLabel").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(2, 8))

        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.grid(row=13, column=0, columnspan=3, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="MOUNT", style="Teal.TButton", command=self.do_mount).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="REFRESH MOUNTS", command=self.refresh_mounted_drives).grid(
            row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Label(right, text="Mounted ImDisk drives", style="Panel.TLabel").grid(
            row=14, column=0, columnspan=3, sticky="w", pady=(16, 6))

        tree_frame = ttk.Frame(right, style="Panel.TFrame")
        tree_frame.grid(row=15, column=0, columnspan=3, sticky="nsew")
        right.rowconfigure(15, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.mount_tree = ttk.Treeview(
            tree_frame,
            columns=("drive", "image", "mode"),
            show="headings",
            height=6,
            selectmode="browse"
        )
        self.mount_tree.heading("drive", text="Drive")
        self.mount_tree.heading("image", text="RAW image")
        self.mount_tree.heading("mode", text="Mode")
        self.mount_tree.column("drive", width=90, anchor="w", stretch=False)
        self.mount_tree.column("image", width=270, anchor="w", stretch=True)
        self.mount_tree.column("mode", width=90, anchor="w", stretch=False)
        self.mount_tree.grid(row=0, column=0, sticky="nsew")

        mount_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.mount_tree.yview)
        mount_scroll.grid(row=0, column=1, sticky="ns")
        self.mount_tree.configure(yscrollcommand=mount_scroll.set)

        mount_actions = ttk.Frame(right, style="Panel.TFrame")
        mount_actions.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        mount_actions.columnconfigure(0, weight=1)
        mount_actions.columnconfigure(1, weight=1)
        ttk.Button(
            mount_actions,
            text="UNMOUNT SELECTED",
            command=self.unmount_selected
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            mount_actions,
            text="OPEN SELECTED",
            command=self.open_selected_mount
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        footer = ttk.Frame(self, padding=(18, 8, 18, 16))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var).pack(fill="x")
        ttk.Label(
            footer,
            text=f"Log: {LOG_PATH}",
            foreground=MUTED
        ).pack(fill="x", pady=(2, 0))
        ttk.Progressbar(footer, variable=self.progress_var, maximum=100).pack(fill="x", pady=(6, 7))
        self.cancel_btn = ttk.Button(footer, text="Cancel", command=self.request_cancel, state="disabled")
        self.cancel_btn.pack(side="right")

    def _refresh_mount_status(self):
        letters = [f"{x}:" for x in available_drive_letters()]
        self.drive_combo.configure(values=letters)

        if self.drive_var.get() not in letters and letters:
            self.drive_var.set(letters[0])

        if find_imdisk():
            self.mount_status_var.set(
                "ImDisk detected — RAW mounting available."
            )
        else:
            self.mount_status_var.set(
                "ImDisk not detected — install it to enable drive-letter mounting."
            )

        if hasattr(self, "mount_tree"):
            self.refresh_mounted_drives()

    def set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.create_btn.configure(state=state)
        self.combine_btn.configure(state=state)
        self.split_existing_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if not busy:
            self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True
        self.status_var.set("Cancelling...")

    def should_stop(self):
        return self.cancel_requested

    def progress(self, current, total, text):
        pct = max(0, min(100, current / max(total, 1) * 100))
        bucket = int(pct // 10)
        if bucket != self._last_logged_progress_bucket:
            self._last_logged_progress_bucket = bucket
            log("進捗 %d%%: %s", int(pct), text)
        self.after(0, lambda: (self.progress_var.set(pct), self.status_var.set(text)))

    def choose_source(self):
        p = filedialog.askdirectory(title="Choose source folder")
        if not p:
            return
        self.source_var.set(p)
        log("元フォルダーを選択: %s", p)
        self.status_var.set("Calculating folder size...")
        threading.Thread(target=self._scan_source, args=(Path(p),), daemon=True).start()

    def _scan_source(self, p: Path):
        try:
            total, files, dirs, largest = folder_stats(p)
            rec = recommended_size_mb(total, files, dirs)
            msg = f"{human_size(total)} • {files} files • {dirs} folders"
            if largest > 0xFFFFFFFF:
                msg += " • contains file > 4 GiB"
            self.after(0, lambda: self.folder_size_var.set(msg))
            if rec:
                self.after(0, lambda: self.card_size_var.set(f"{rec} MB"))
                self.after(0, lambda: self.status_var.set(f"Recommended size: {rec} MB"))
            else:
                self.after(0, lambda: self.status_var.set("Folder exceeds the supported 32 GiB image sizes."))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(APP_NAME, str(e)))

    def choose_output(self):
        p = filedialog.askdirectory(title="Choose output folder")
        if p:
            self.output_dir_var.set(p)
            log("出力フォルダーを選択: %s", p)

    def choose_part(self):
        p = filedialog.askopenfilename(
            title="Select .raw.001",
            filetypes=[("Split RAW first part", "*.raw.001"), ("All files", "*.*")]
        )
        if not p:
            return
        path = Path(p)
        self.part_var.set(str(path))
        try:
            base, parts = discover_parts(path)
            total = sum(x.stat().st_size for x in parts)
            self.parts_info_var.set(f"{len(parts)} part(s) • {human_size(total)} total")
            self.join_output_var.set(str(base))
        except Exception as e:
            self.parts_info_var.set(str(e))

    def choose_join_output(self):
        initial = Path(self.join_output_var.get()).name if self.join_output_var.get() else "sd.raw"
        p = filedialog.asksaveasfilename(title="Save combined RAW", defaultextension=".raw",
                                         initialfile=initial,
                                         filetypes=[("RAW image", "*.raw"), ("All files", "*.*")])
        if p:
            self.join_output_var.set(p)

    def choose_existing_raw(self):
        p = filedialog.askopenfilename(
            title="Choose existing RAW image",
            filetypes=[("RAW image", "*.raw"), ("All files", "*.*")]
        )
        if not p:
            return
        path = Path(p)
        self.split_existing_var.set(str(path))
        try:
            self.split_existing_info_var.set(
                f"{human_size(path.stat().st_size)} • parts will be max 4000 MiB"
            )
        except Exception:
            self.split_existing_info_var.set("RAW selected")

    def start_split_existing(self):
        if self.busy:
            return

        raw = Path(self.split_existing_var.get())
        if not raw.is_file():
            messagebox.showerror(APP_NAME, "Choose an existing .raw file to split.")
            return


        first_part = raw.with_name(raw.name + ".001")
        if first_part.exists():
            if not messagebox.askyesno(
                APP_NAME,
                f"Split parts already exist for:\\n{raw.name}\\n\\nOverwrite them?"
            ):
                return

        self.set_busy(True)
        self._last_logged_progress_bucket = -1
        self.progress_var.set(0)
        threading.Thread(
            target=self._split_existing_worker,
            args=(raw,),
            daemon=True
        ).start()

    def _split_existing_worker(self, raw: Path):
        try:

            i = 1
            while True:
                p = raw.with_name(raw.name + f".{i:03d}")
                if not p.exists():
                    break
                p.unlink()
                i += 1

            parts = split_raw(
                raw,
                progress_cb=self.progress,
                stop_cb=self.should_stop
            )

            if not self.keep_original_split_var.get():
                raw.unlink(missing_ok=True)

            self.after(0, lambda: self.progress_var.set(100))
            self.after(0, lambda: self.status_var.set("Done"))
            self.after(0, lambda: messagebox.showinfo(
                APP_NAME,
                f"Created {len(parts)} split part(s) in:\\n{raw.parent}"
            ))
        except Exception as e:
            if str(e) == "Cancelled":
                self.after(0, lambda: self.status_var.set("Cancelled"))
            else:
                log_exception("既存 RAW の分割に失敗", e)
                self.after(0, lambda: self.status_var.set("Error"))
                self.after(0, lambda: messagebox.showerror(
                    APP_NAME,
                    f"{type(e).__name__}: {e}"
                ))
        finally:
            self.after(0, lambda: self.set_busy(False))

    def choose_mount_raw(self):
        p = filedialog.askopenfilename(
            title="Choose RAW image",
            filetypes=[
                ("RAW / split RAW", "*.raw *.raw.001 *.img *.dd *.001"),
                ("RAW image", "*.raw"),
                ("Split RAW first part", "*.001"),
                ("All files", "*.*"),
            ]
        )
        if p:
            self.mount_raw_var.set(p)

    def do_mount(self):
        raw = Path(self.mount_raw_var.get())
        if not raw.is_file():
            messagebox.showerror(APP_NAME, "Choose an existing .raw image.")
            return
        try:
            drive = mount_raw(raw, self.drive_var.get(), self.read_only_var.get())
            self.session_mounts[drive.upper()] = {
                "drive": drive.upper(),
                "image": str(raw),
                "mode": "Read-only" if self.read_only_var.get() else "Read/write",
            }
            log("マウント成功: %s -> %s", raw, drive)
            self.mount_status_var.set(f"Mounted {raw.name} as {drive}")
            self.status_var.set(f"Mounted {drive}")
            try:
                os.startfile(drive + "\\")
            except Exception:
                pass
        except Exception as e:
            log_exception("マウント処理に失敗", e)
            messagebox.showerror(APP_NAME, str(e))
        finally:
            self._refresh_mount_status()

    def refresh_mounted_drives(self):
        if not hasattr(self, "mount_tree"):
            return

        for item in self.mount_tree.get_children():
            self.mount_tree.delete(item)

        if not find_imdisk():
            self.mount_status_var.set(
                "ImDisk not detected — install it to enable drive-letter mounting."
            )
            return

        try:
            mounts = list_imdisk_mounts()

            by_drive = {}
            no_drive = []

            for mount in mounts:
                drive = mount.get("drive", "").upper()
                if drive:
                    by_drive[drive] = mount
                else:
                    no_drive.append(mount)

            for drive, remembered in list(self.session_mounts.items()):
                if os.path.exists(drive + "\\"):
                    if drive not in by_drive:
                        by_drive[drive] = {
                            "unit": "",
                            "drive": drive,
                            "image": remembered.get("image", ""),
                            "mode": remembered.get("mode", ""),
                        }
                else:
                    self.session_mounts.pop(drive, None)

            for drive in sorted(by_drive):
                mount = by_drive[drive]
                unit = mount.get("unit", "")
                iid = f"unit:{unit}" if unit else f"drive:{drive}"
                self.mount_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        drive,
                        mount.get("image") or "(image path not reported)",
                        mount.get("mode") or ""
                    )
                )

            for mount in no_drive:
                unit = mount.get("unit", "")
                self.mount_tree.insert(
                    "",
                    "end",
                    iid=f"unit:{unit}",
                    values=(
                        f"Unit {unit}",
                        mount.get("image") or "(image path not reported)",
                        mount.get("mode") or ""
                    )
                )

            self.mount_status_var.set(
                f"ImDisk detected — {len(by_drive) + len(no_drive)} mounted image(s)."
            )

        except Exception as e:
            log_exception("ImDisk マウント一覧の更新に失敗", e)
            self.mount_status_var.set(f"Could not query ImDisk: {e}")

    def _selected_mount(self):
        selection = self.mount_tree.selection()
        if not selection:
            return None

        iid = selection[0]
        values = self.mount_tree.item(iid, "values")
        unit = iid.split(":", 1)[1] if iid.startswith("unit:") else ""
        drive = values[0] if values else ""
        if drive.startswith("Unit "):
            drive = ""

        return {
            "unit": unit,
            "drive": drive,
            "values": values,
        }

    def unmount_selected(self):
        selected = self._selected_mount()
        if not selected:
            messagebox.showinfo(
                APP_NAME,
                "Select a mounted RAW drive from the list first."
            )
            return

        label = selected["drive"] or f"ImDisk unit {selected['unit']}"

        try:
            if selected["drive"]:
                unmount_raw(selected["drive"])
                self.session_mounts.pop(selected["drive"].upper(), None)
            elif selected["unit"]:
                result = _run_imdisk(
                    ["-d", "-u", selected["unit"]],
                    purpose=f"ユニット {selected['unit']} アンマウント"
                )
                if result.returncode != 0:
                    forced = _run_imdisk(
                        ["-D", "-u", selected["unit"]],
                        purpose=f"ユニット {selected['unit']} 強制アンマウント"
                    )
                    if forced.returncode != 0:
                        raise RuntimeError(
                            (forced.stderr or forced.stdout or
                             result.stderr or result.stdout or
                             "ImDisk failed to detach the selected unit.")
                        )

            log("アンマウント成功: %s", label)
            self.status_var.set(f"Unmounted {label}")

        except Exception as e:
            log_exception("アンマウント処理に失敗", e)
            messagebox.showerror(APP_NAME, str(e))
        finally:
            self._refresh_mount_status()


    def open_selected_mount(self):
        selected = self._selected_mount()
        if not selected:
            messagebox.showinfo(APP_NAME, "Select a mounted RAW drive from the list first.")
            return
        try:
            os.startfile(selected["drive"] + "\\")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not open {selected['drive']}\\n\\n{e}")

    def start_create(self):
        if self.busy:
            return
        src = Path(self.source_var.get())
        if not src.is_dir():
            messagebox.showerror(APP_NAME, "Choose a valid source folder.")
            return

        out_text = self.output_dir_var.get().strip()
        if not out_text:
            messagebox.showerror(APP_NAME, "Choose an output folder.")
            return

        out_dir = Path(out_text)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not create output folder:\n{e}")
            return

        name = sanitize_name(self.card_name_var.get())
        raw_path = out_dir / f"{name}.raw"


        try:
            src_resolved = src.resolve()
            out_resolved = raw_path.resolve(strict=False)
            if out_resolved == src_resolved:
                raise ValueError("Output RAW cannot be the source folder.")
        except Exception:
            pass

        self.set_busy(True)
        self._last_logged_progress_bucket = -1
        self.progress_var.set(0)
        threading.Thread(target=self._create_worker, args=(src, raw_path, name), daemon=True).start()

    def _create_worker(self, src: Path, raw_path: Path, name: str):
        try:
            total, files, dirs, largest = folder_stats(src)
            if largest > 0xFFFFFFFF:
                raise ValueError("The source contains a file larger than FAT32's 4 GiB per-file limit.")

            if self.card_size_var.get() == "Auto":
                first = recommended_size_mb(total, files, dirs)
            else:
                first = int(self.card_size_var.get().split()[0])

            if first is None:
                raise ValueError("The source folder is too large for the maximum 32768 MB card.")

            candidates = [x for x in ALLOWED_MB if x >= first]
            capacity_error = None

            for size_mb in candidates:
                if self.should_stop():
                    raise RuntimeError("Cancelled")
                try:
                    self.progress(0, 1, f"Creating {size_mb} MB virtual SD...")
                    create_raw_image(src, raw_path, size_mb, make_volume_label(name),
                                     progress_cb=self.progress, stop_cb=self.should_stop)
                    capacity_error = None
                    break
                except InsufficientStorage as e:
                    capacity_error = e
                    raw_path.unlink(missing_ok=True)
                    continue

            if capacity_error is not None or not raw_path.exists():
                raise RuntimeError(
                    "The source files did not fit in any remaining allowed card size.\n"
                    f"Last capacity error: {capacity_error}"
                )

            if self.split_var.get():
                parts = split_raw(raw_path, progress_cb=self.progress, stop_cb=self.should_stop)
                raw_path.unlink(missing_ok=True)
                result = f"Created {len(parts)} split part(s) in:\n{raw_path.parent}"
            else:
                result = f"Created:\n{raw_path}"

            self.after(0, lambda: self.progress_var.set(100))
            self.after(0, lambda: self.status_var.set("Done"))
            self.after(0, lambda: messagebox.showinfo(APP_NAME, result))
        except Exception as e:
            raw_path.unlink(missing_ok=True)
            if str(e) == "Cancelled":
                self.after(0, lambda: self.status_var.set("Cancelled"))
            else:
                log_exception("仮想 SD 作成に失敗", e)
                detail = f"{type(e).__name__}: {e}"
                self.after(0, lambda: self.status_var.set("Error"))
                self.after(0, lambda d=detail: messagebox.showerror(
                    APP_NAME,
                    "Virtual SD creation failed.\n\n"
                    + d
                    + "\n\nCheck that the output folder is writable and has enough free disk space."
                ))
        finally:
            self.after(0, lambda: self.set_busy(False))

    def start_combine(self):
        if self.busy:
            return
        first = Path(self.part_var.get())
        if not first.is_file():
            messagebox.showerror(APP_NAME, "Choose a valid .raw.001 file.")
            return

        output = Path(self.join_output_var.get())
        if not output.name:
            messagebox.showerror(APP_NAME, "Choose an output RAW file.")
            return

        self.set_busy(True)
        self._last_logged_progress_bucket = -1
        self.progress_var.set(0)
        threading.Thread(target=self._combine_worker, args=(first, output), daemon=True).start()

    def _combine_worker(self, first: Path, output: Path):
        try:
            combine_parts(first, output, progress_cb=self.progress, stop_cb=self.should_stop)
            self.after(0, lambda: self.progress_var.set(100))
            self.after(0, lambda: self.status_var.set("Done"))
            self.after(0, lambda: messagebox.showinfo(APP_NAME, f"Created:\n{output}"))
        except Exception as e:
            output.unlink(missing_ok=True)
            if str(e) == "Cancelled":
                self.after(0, lambda: self.status_var.set("Cancelled"))
            else:
                log_exception("RAW 結合に失敗", e)
                self.after(0, lambda: self.status_var.set("Error"))
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"{type(e).__name__}: {e}"))
        finally:
            self.after(0, lambda: self.set_busy(False))


if __name__ == "__main__":
    App().mainloop()
