"""Bounded, read-only-publication diagnostic of one existing book build.

Only a disposable checkout is changed. No publisher, approval, finalizer, or
release transport is called. Result files are explicitly not release evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import threading
import time

SOURCE_COMMIT = "1a129c5414dbc1cf7cef5e1fdb16f1b3cbb2561e"
REPOSITORY = "blaghtayt-alt/iman-companion"
CHILD_TIMEOUT = 600


def event(kind, **data):
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                      "diagnostic": kind, **data}, ensure_ascii=False), flush=True)


def traced_renderer(arguments):
    target = (Path.cwd() / "books/render_uno.py").resolve()
    source = target.read_text(encoding="utf8").splitlines()
    needles = {
        "doc=desktop.loadComponentFromURL": "UNO open document",
        "doc.getTextFields().refresh()": "UNO refresh text fields",
        "paragraphs=doc.getText().createEnumeration()": "UNO begin RTL paragraphs",
        "native_footer(doc,languages": "UNO native footer after RTL paragraphs",
        "doc.calculateAll()": "UNO calculate document",
        "cursor.jumpToLastPage()": "UNO calculate final page",
        "indexes.getByIndex(i).update()": "UNO update contents",
        "state=(page_count": "UNO read contents state",
        "doc.store()": "UNO save DOCX",
        "label_native_contents(doc)": "UNO label contents",
        "doc.storeToURL(": "UNO export PDF",
        "finally:doc.close(True)": "UNO close document",
        "if desktop:desktop.terminate()": "UNO terminate desktop",
        "process.terminate()": "Terminate owned LibreOffice process",
    }
    stages = {n: label for n, line in enumerate(source, 1)
              for needle, label in needles.items() if needle in line}
    previous = None

    def trace(frame, action, value):
        nonlocal previous
        if frame.f_code.co_filename != str(target) or frame.f_code.co_name != "main":
            return None
        if action in {"line", "return", "exception"} and previous:
            label, started, line = previous
            event("uno-stage-end", stage=label, line=line,
                  seconds=round(time.monotonic() - started, 3), action=action)
            previous = None
        if action == "line" and frame.f_lineno in stages:
            label = stages[frame.f_lineno]
            event("uno-stage-start", stage=label, line=frame.f_lineno,
                  file=str(frame.f_locals.get("file", "")),
                  attempt=frame.f_locals.get("attempt"))
            previous = (label, time.monotonic(), frame.f_lineno)
        return trace

    sys.path.insert(0, str(target.parent))
    sys.argv = [str(target), *arguments]
    sys.settrace(trace)
    try:
        runpy.run_path(str(target), run_name="__main__")
    finally:
        sys.settrace(None)


def bounded_runner(log_dir, probe):
    sequence = 0

    def run(arguments, root, **kwargs):
        nonlocal sequence
        if kwargs:
            raise ValueError("Unexpected diagnostic subprocess options")
        sequence += 1
        original = [str(value) for value in arguments]
        command = original[:]
        if len(command) > 1 and command[1] == "books/render_uno.py":
            command = [command[0], "-u", str(probe), "--trace-renderer", *command[2:]]
        label = Path(original[1]).name if len(original) > 1 else original[0]
        prefix = log_dir / f"{sequence:02d}-{label}"
        started = time.monotonic()
        event("command-start", sequence=sequence, command=original, timeout=CHILD_TIMEOUT)
        captured = {"stdout": [], "stderr": []}

        def pump(stream, name, file):
            for line in stream:
                file.write(line)
                file.flush()
                captured[name].append(line)
                print(f"[{sequence:02d} {name}] {line}", end="", flush=True)
            stream.close()

        with prefix.with_suffix(prefix.suffix + ".stdout.log").open("w", encoding="utf8") as stdout_file, \
             prefix.with_suffix(prefix.suffix + ".stderr.log").open("w", encoding="utf8") as stderr_file:
            process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf8",
                                       errors="replace", start_new_session=True,
                                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
            threads = [threading.Thread(target=pump, args=(process.stdout, "stdout", stdout_file)),
                       threading.Thread(target=pump, args=(process.stderr, "stderr", stderr_file))]
            for thread in threads:
                thread.start()
            timed_out = False
            try:
                process.wait(timeout=CHILD_TIMEOUT)
            except subprocess.TimeoutExpired:
                timed_out = True
                event("command-timeout", sequence=sequence, label=label, owned_process_group=process.pid)
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                # This is the new session created above, never a shared process.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
            finally:
                for thread in threads:
                    thread.join(timeout=10)
            event("command-end", sequence=sequence, command=original,
                  seconds=round(time.monotonic() - started, 3),
                  returncode=process.returncode, timedOut=timed_out)
        stdout = "".join(captured["stdout"])
        stderr = "".join(captured["stderr"])
        if timed_out:
            raise RuntimeError(f"Diagnostic child {label} exceeded {CHILD_TIMEOUT}s; owned group terminated")
        if process.returncode:
            raise RuntimeError(f"Diagnostic child {label} failed ({process.returncode})\n{stderr[-3500:]}\n{stdout[-1000:]}")
        return stdout

    return run


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--trace-renderer":
        traced_renderer(sys.argv[2:])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "ur"), required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    log_dir = out / "command-logs"
    log_dir.mkdir(exist_ok=True)
    (out / "NOT-PUBLICATION.txt").write_text(
        "Diagnostic only. No source approval, Microsoft Word receipt, final visual acceptance, "
        "release publication, or production preparation queue is supplied.\n", encoding="utf8")
    # Prevent diagnostic records from claiming the production artifact namespace.
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(root / "books"))
    import automatic_publication
    original_scopes = automatic_publication.scopes
    scope = (args.language, "tadabbur-extended")

    def selected_scopes(path, for_release=False):
        result = [row for row in original_scopes(path, for_release)
                  if (row["language"], row["collection"]) == scope]
        if len(result) != 1:
            raise ValueError("Diagnostic requires exactly one existing eligible scope")
        return result

    automatic_publication.scopes = selected_scopes
    automatic_publication.run = bounded_runner(log_dir, Path(__file__).resolve())
    event("scope-start", language=scope[0], collection=scope[1], sourceCommit=SOURCE_COMMIT)
    started = time.monotonic()
    report = automatic_publication.build(root, out, SOURCE_COMMIT, REPOSITORY,
                                         "DIAGNOSTIC-NOT-PUBLICATION")
    event("scope-end", language=scope[0], collection=scope[1],
          seconds=round(time.monotonic() - started, 3),
          prepared=report["prepared"], failed=report["failed"], unchanged=report["unchanged"])
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
